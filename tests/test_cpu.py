import unittest

from decimal_iron.cpu import CPUFault, GROUP_MARK, ReferenceCPU, WORD_MARK


class ReferenceCPUTests(unittest.TestCase):
    def test_variable_length_wordmarks_and_bcd_add_subtract(self):
        cpu = ReferenceCPU()
        cpu.write_field(100, 9_999)
        cpu.write_field(110, 1)
        cpu.load_program([("LDA", 100), ("ADD", 110), ("STA", 120), ("SUB", 110), ("HALT", 0)])
        self.assertEqual(cpu.run(), 5)
        self.assertEqual(cpu.read_field(120), 10_000)
        self.assertEqual(cpu.accumulator, 9_999)
        self.assertTrue(cpu.examine(100).wordmark)
        self.assertEqual(cpu.memory[104] & 0x0F, GROUP_MARK)

    def test_branch_and_channel_instructions(self):
        cpu = ReferenceCPU()
        cpu.write_field(100, 0)
        cpu.channel_input.append(4250)
        cpu.load_program(
            [
                ("IN", 0),
                ("STA", 110),
                ("LDA", 100),
                ("JZ", 20),
                ("HALT", 0),
                ("LDA", 110),
                ("OUT", 0),
                ("HALT", 0),
            ]
        )
        cpu.run()
        self.assertEqual(cpu.read_field(110), 4250)
        self.assertEqual(cpu.channel_output, [4250])
        self.assertEqual(cpu.last_mnemonic, "HALT")

    def test_transfer_is_double_entry_and_atomic(self):
        cpu = ReferenceCPU()
        cpu.transfer("FI01", "FI02", 12_345)
        cpu.transfer("FI02", "FI03", 2_000)
        self.assertEqual(cpu.account_balances(), {"FI01": -12_345, "FI02": 10_345, "FI03": 2_000})
        self.assertEqual(sum(cpu.account_balances().values()), 0)

        before = cpu.account_balances()
        with self.assertRaises(CPUFault):
            cpu.transfer("FI01", "FI01", 10)
        self.assertEqual(cpu.account_balances(), before)

    def test_deposit_is_confined_to_panel_scratch(self):
        cpu = ReferenceCPU()
        cpu.deposit_scratch(249, 7)
        self.assertEqual(cpu.examine(249).character, 7)
        with self.assertRaises(CPUFault):
            cpu.deposit_scratch(100, 7)


if __name__ == "__main__":
    unittest.main()
