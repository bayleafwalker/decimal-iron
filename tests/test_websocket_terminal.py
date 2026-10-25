import threading
import unittest
from http.server import ThreadingHTTPServer

from decimal_iron.adapter import TerminalPaymentAdapter
from decimal_iron.machine import DecimalMachine
from decimal_iron.terminal import TerminalSession
from decimal_iron.web import make_handler
from decimal_iron.websocket_client import WebSocketTerminal


class WebSocketTerminalTests(unittest.TestCase):
    def test_real_socket_adapter_posts_only_through_terminal_bytes(self):
        machine = DecimalMachine()
        setup = TerminalSession(machine)
        setup.feed(b"KEY OPEN\rOPEN 1982-10-01\r")
        setup.take_output()
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(machine))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        terminal = None
        try:
            terminal = WebSocketTerminal(f"ws://127.0.0.1:{server.server_port}/terminal")
            adapter = TerminalPaymentAdapter(terminal)
            receipt = adapter.post_payment("SOCKET-1", "FI01", "FI02", 2000)
            self.assertEqual(receipt.payment_id, "SOCKET-1")
            self.assertEqual(len(machine.transactions), 1)
            self.assertFalse(hasattr(adapter, "machine"))
        finally:
            if terminal is not None:
                terminal.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
