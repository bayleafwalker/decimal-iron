import unittest

from decimal_iron.adapter import MemoryTerminalChannel, TerminalPaymentAdapter, TerminalTimeout
from decimal_iron.machine import DecimalMachine
from decimal_iron.terminal import TerminalSession


class DropAfterProcessing:
    def __init__(self, channel):
        self.channel = channel
        self.drop = True

    def write(self, data):
        self.channel.write(data)

    def read(self, timeout=2.0):
        frame = self.channel.read(timeout)
        if self.drop:
            self.drop = False
            raise TerminalTimeout("ack lost")
        return frame


class FailBeforeProcessing:
    def __init__(self, channel):
        self.channel = channel
        self.fail = True

    def write(self, data):
        if self.fail and data.startswith(b"PAY "):
            self.fail = False
            raise TerminalTimeout("write outcome unknown to adapter")
        self.channel.write(data)

    def read(self, timeout=2.0):
        return self.channel.read(timeout)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.machine = DecimalMachine()
        self.session = TerminalSession(self.machine)
        self.channel = MemoryTerminalChannel(self.session)
        self.channel.write(b"KEY OPEN\rOPEN 1982-10-01\r")
        self.channel.read()

    def test_lost_ack_is_resolved_by_inquiry_without_double_post(self):
        adapter = TerminalPaymentAdapter(DropAfterProcessing(self.channel))
        receipt = adapter.post_payment("T001", "FI01", "FI02", 1200)
        self.assertEqual(receipt.resolution, "RECOVERED_BY_INQUIRY")
        self.assertEqual(len(self.machine.transactions), 1)
        self.assertEqual(self.machine.transactions["T001"]["seq"], receipt.journal_sequence)
        self.assertFalse(hasattr(adapter, "machine"))

    def test_not_found_retries_exact_same_idempotency_identity(self):
        adapter = TerminalPaymentAdapter(FailBeforeProcessing(self.channel))
        receipt = adapter.post_payment("T002", "FI01", "FI02", 1200)
        self.assertEqual(receipt.resolution, "RETRIED_AFTER_NOT_FOUND")
        self.assertEqual(len(self.machine.transactions), 1)
        self.assertIn("T002", self.machine.transactions)


if __name__ == "__main__":
    unittest.main()
