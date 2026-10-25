import json
import unittest
from pathlib import Path

from decimal_iron.cpu import ReferenceCPU


class TransferVectorTests(unittest.TestCase):
    def test_shared_vectors_match_software_decimal_cpu(self):
        vectors = json.loads((Path(__file__).parents[1] / "vectors" / "transaction_vectors.json").read_text(encoding="ascii"))
        for vector in vectors:
            with self.subTest(vector=vector["name"]):
                cpu = ReferenceCPU()
                source_address = cpu.ensure_account("SRC")
                destination_address = cpu.ensure_account("DST")
                cpu.write_field(source_address, vector["source_balance"])
                cpu.write_field(destination_address, vector["destination_balance"])
                cpu.transfer("SRC", "DST", vector["amount_minor"])
                balances = cpu.account_balances()
                self.assertEqual(balances["SRC"], vector["source_balance"] - vector["amount_minor"])
                self.assertEqual(balances["DST"], vector["destination_balance"] + vector["amount_minor"])
                self.assertEqual(sum(balances.values()), vector["source_balance"] + vector["destination_balance"])


if __name__ == "__main__":
    unittest.main()
