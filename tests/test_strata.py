import unittest

from decimal_iron.strata import PaymentInstruction, build_protocol_trace, decode_host_record


class ProtocolStrataTests(unittest.TestCase):
    def setUp(self):
        self.instruction = PaymentInstruction.from_mapping(
            {
                "payment_id": "BANK-1-000000000001",
                "bank_id": "BANK-1",
                "source": "FI01",
                "destination": "FI02",
                "currency": "FIM",
                "amount_minor": 12_345,
            }
        )

    def test_fixed_record_round_trip_preserves_identity_and_minor_units(self):
        trace = build_protocol_trace(self.instruction)
        self.assertEqual(len(trace.host_record), 96)
        self.assertEqual(decode_host_record(trace.host_record), self.instruction)
        self.assertEqual(trace.terminal_command, "PAY BANK-1-000000000001 FI01 FI02 FIM 12345")
        self.assertEqual(trace.host_checksum, trace.host_record[74:90])

    def test_host_record_checksum_and_amount_are_validated(self):
        record = build_protocol_trace(self.instruction).host_record
        with self.assertRaisesRegex(ValueError, "checksum"):
            decode_host_record(record[:65] + ("9" if record[65] != "9" else "8") + record[66:])
        with self.assertRaisesRegex(ValueError, "ASCII columns"):
            decode_host_record(record[:-1])

    def test_request_rejects_floating_amount_and_non_fim_currency(self):
        request = self.instruction.fields()
        request["amount_minor"] = 12.5
        with self.assertRaisesRegex(ValueError, "integer"):
            PaymentInstruction.from_mapping(request)
        request["amount_minor"] = 1250
        request["currency"] = "EUR"
        with self.assertRaisesRegex(ValueError, "currency"):
            PaymentInstruction.from_mapping(request)


if __name__ == "__main__":
    unittest.main()
