import json
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

from decimal_iron.adapter import TerminalPaymentAdapter
from decimal_iron.gateway import GatewayService, make_gateway_handler
from decimal_iron.machine import DecimalMachine
from decimal_iron.terminal import TerminalSession
from decimal_iron.web import make_handler
from decimal_iron.websocket_client import WebSocketTerminal


class FullStackTests(unittest.TestCase):
    def test_bank_json_reaches_journal_only_through_gateway_and_terminal(self):
        machine = DecimalMachine()
        operator = TerminalSession(machine)
        operator.feed(b"KEY OPEN\rOPEN 1982-10-01\r")
        operator.take_output()

        processor = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(machine))
        processor_thread = threading.Thread(target=processor.serve_forever, daemon=True)
        processor_thread.start()
        terminal = WebSocketTerminal(f"ws://127.0.0.1:{processor.server_port}/terminal")
        service = GatewayService(TerminalPaymentAdapter(terminal), max_queue=4)
        service.start()
        gateway = ThreadingHTTPServer(("127.0.0.1", 0), make_gateway_handler(service))
        gateway_thread = threading.Thread(target=gateway.serve_forever, daemon=True)
        gateway_thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{gateway.server_port}/readyz", timeout=2) as response:
                readiness = json.loads(response.read())
            self.assertEqual(readiness["processor_phase"], "OPEN")
            payload = {
                "payment_id": "BANK-2-000000000001",
                "bank_id": "BANK-2",
                "source": "FI01",
                "destination": "FI02",
                "currency": "FIM",
                "amount_minor": 2750,
            }
            request = urllib.request.Request(
                f"http://127.0.0.1:{gateway.server_port}/payments",
                data=json.dumps(payload).encode("ascii"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                self.assertEqual(response.status, 202)
                queued = json.loads(response.read())
            self.assertIn(queued["status"], {"QUEUED", "PROCESSING", "POSTED"})

            deadline = time.monotonic() + 2
            status = None
            while time.monotonic() < deadline:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{gateway.server_port}/payments/{payload['payment_id']}", timeout=2
                ) as response:
                    status = json.loads(response.read())
                if status["status"] == "POSTED":
                    break
                time.sleep(0.01)

            self.assertEqual(status["status"], "POSTED")
            self.assertEqual(status["receipt"]["journal_sequence"], machine.transactions[payload["payment_id"]]["seq"])
            self.assertEqual(machine.positions["FI01"], -2750)
            self.assertEqual(machine.positions["FI02"], 2750)
            self.assertEqual([layer["name"] for layer in status["protocol"]["layers"]], [
                "cloud-json-v1", "xml-clearing-2001", "fixed-host-record-1982", "terminal-24x80-v1"
            ])
            with urllib.request.urlopen(f"http://127.0.0.1:{gateway.server_port}/payments?limit=1", timeout=2) as response:
                projection = json.loads(response.read())
            self.assertEqual(projection["payments"][0]["payment_id"], payload["payment_id"])
        finally:
            gateway.shutdown()
            gateway.server_close()
            service.close()
            terminal.close()
            processor.shutdown()
            processor.server_close()
            gateway_thread.join(timeout=1)
            processor_thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
