import tempfile
import time
import unittest
from pathlib import Path

from decimal_iron.adapter import MemoryTerminalChannel, TerminalPaymentAdapter
from decimal_iron.adapter import PaymentReceipt, UnknownOutcome
from decimal_iron.gateway import GatewayService
from decimal_iron.machine import DecimalMachine
from decimal_iron.terminal import TerminalSession


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.machine = DecimalMachine()
        channel = MemoryTerminalChannel(TerminalSession(self.machine))
        channel.write(b"KEY OPEN\rOPEN 1982-10-01\r")
        channel.read()
        self.adapter = TerminalPaymentAdapter(channel)
        self.payment = {
            "payment_id": "BANK-1-000000000001",
            "bank_id": "BANK-1",
            "source": "FI01",
            "destination": "FI02",
            "amount_minor": 1200,
            "currency": "FIM",
        }

    def test_same_identity_is_idempotent_and_different_payload_conflicts(self):
        service = GatewayService(self.adapter, max_queue=2)
        self.addCleanup(service.close)
        first_status, first = service.submit(self.payment)
        duplicate_status, duplicate = service.submit(self.payment)
        self.assertEqual(first_status, 202)
        self.assertEqual(duplicate_status, 202)
        self.assertEqual(first["payment_id"], duplicate["payment_id"])

        conflict = {**self.payment, "amount_minor": 1201}
        status, result = service.submit(conflict)
        self.assertEqual(status, 409)
        self.assertEqual(result["error"], "IDEMPOTENCY_CONFLICT")

    def test_bounded_queue_returns_retryable_full_response(self):
        service = GatewayService(self.adapter, max_queue=1)
        self.addCleanup(service.close)
        self.assertEqual(service.submit(self.payment)[0], 202)
        second = {**self.payment, "payment_id": "BANK-1-000000000002"}
        status, result = service.submit(second)
        self.assertEqual(status, 503)
        self.assertEqual(result["error"], "QUEUE_FULL")

    def test_durable_outbox_restarts_through_the_terminal_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "gateway.sqlite3"
            first = GatewayService(self.adapter, max_queue=2, state_path=state)
            first.submit(self.payment)
            first.close()

            recovered = GatewayService(self.adapter, max_queue=2, state_path=state)
            recovered.start()
            try:
                deadline = time.monotonic() + 2
                result = recovered.status(self.payment["payment_id"])
                while result and result["status"] in {"QUEUED", "PROCESSING"} and time.monotonic() < deadline:
                    time.sleep(0.01)
                    result = recovered.status(self.payment["payment_id"])
                self.assertIsNotNone(result)
                self.assertEqual(result["status"], "POSTED")
                self.assertEqual(self.machine.transactions[self.payment["payment_id"]]["amount_minor"], 1200)
            finally:
                recovered.close()

    def test_unknown_outcome_can_be_reconciled_by_same_identity_retry(self):
        class OneUncertainReply:
            def __init__(self):
                self.calls = 0

            def post_payment(self, payment_id, source, destination, amount_minor, *, currency="FIM"):
                self.calls += 1
                if self.calls == 1:
                    raise UnknownOutcome("first terminal inquiry was unavailable")
                return PaymentReceipt(payment_id, 42, "IDEMPOTENT_DUPLICATE")

            def processor_status(self):
                return "OPEN"

        adapter = OneUncertainReply()
        service = GatewayService(adapter, max_queue=2)
        service.start()
        try:
            self.assertEqual(service.submit(self.payment)[0], 202)
            deadline = time.monotonic() + 2
            result = service.status(self.payment["payment_id"])
            while result and result["status"] != "UNKNOWN_OUTCOME" and time.monotonic() < deadline:
                time.sleep(0.01)
                result = service.status(self.payment["payment_id"])
            self.assertEqual(result["status"], "UNKNOWN_OUTCOME")

            self.assertEqual(service.submit(self.payment)[0], 202)
            deadline = time.monotonic() + 2
            result = service.status(self.payment["payment_id"])
            while result and result["status"] != "POSTED" and time.monotonic() < deadline:
                time.sleep(0.01)
                result = service.status(self.payment["payment_id"])
            self.assertEqual(result["status"], "POSTED")
            self.assertEqual(adapter.calls, 2)
        finally:
            service.close()

    def test_timed_out_close_keeps_database_open_until_blocked_worker_exits(self):
        class BlockedAdapter:
            def __init__(self):
                import threading

                self.entered = threading.Event()
                self.release = threading.Event()

            def post_payment(self, payment_id, source, destination, amount_minor, *, currency="FIM"):
                self.entered.set()
                if not self.release.wait(2):
                    raise TimeoutError("test adapter was not released")
                return PaymentReceipt(payment_id, 17, "ACKNOWLEDGED")

            def processor_status(self):
                return "OPEN"

        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "gateway.sqlite3"
            adapter = BlockedAdapter()
            service = GatewayService(adapter, max_queue=2, state_path=state)
            service.start()
            self.assertEqual(service.submit(self.payment)[0], 202)
            self.assertTrue(adapter.entered.wait(1), "worker did not enter the blocked adapter")

            queued = {**self.payment, "payment_id": "BANK-1-000000000002"}
            self.assertEqual(service.submit(queued)[0], 202)
            self.assertFalse(service.close(timeout=0.01))
            self.assertEqual(service.status(self.payment["payment_id"])["status"], "PROCESSING")
            self.assertEqual(service.submit({**self.payment, "payment_id": "BANK-1-000000000003"})[0], 503)

            adapter.release.set()
            service._thread.join(1)
            self.assertFalse(service._thread.is_alive())
            self.assertTrue(service.close())

            recovered = GatewayService(adapter, max_queue=2, state_path=state)
            try:
                self.assertEqual(recovered.status(self.payment["payment_id"])["status"], "POSTED")
                self.assertEqual(recovered.status(queued["payment_id"])["status"], "QUEUED")
            finally:
                recovered.close()


if __name__ == "__main__":
    unittest.main()
