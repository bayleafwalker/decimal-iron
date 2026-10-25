"""Software reference for the character-addressed decimal processor.

Memory stores one decimal/zone character per byte. Bit 7 is the word mark,
bit 4 is the sign on a word's first character, and the low nibble is the
character code. Numeric words are variable length and terminate with group
mark 0xC. The small ISA is intentionally not IBM 1401 compatible.
"""

from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass

MEMORY_SIZE = 256
WORD_MARK = 0x80
NEGATIVE = 0x10
GROUP_MARK = 0x0C
FIELD_WIDTH = 12
ACCOUNT_START = 32
ACCOUNT_STRIDE = 14
ACCOUNT_CAPACITY = 14
AMOUNT_ADDRESS = 236
PANEL_SCRATCH_START = 249

OPCODES = {
    "HALT": 0x0,
    "LDA": 0x1,
    "STA": 0x2,
    "ADD": 0x3,
    "SUB": 0x4,
    "JMP": 0x5,
    "JZ": 0x6,
    "JN": 0x7,
    "IN": 0x8,
    "OUT": 0x9,
    "CMP": 0xA,
    "NOP": 0xB,
}
MNEMONICS = {value: key for key, value in OPCODES.items()}


class CPUFault(RuntimeError):
    """Invalid decimal instruction, word mark, channel or address."""


@dataclass(frozen=True)
class MemoryCell:
    character: int
    wordmark: bool
    negative: bool


class ReferenceCPU:
    """Micro-operation-level software model used by the ledger and panel."""

    def __init__(self) -> None:
        self.memory = bytearray(MEMORY_SIZE)
        self.account_addresses: dict[str, int] = {}
        self.pc = 0
        self.ar = 0
        self.ir = 0
        self.accumulator = 0
        self.zero_flag = True
        self.negative_flag = False
        self.carry_flag = False
        self.overflow_flag = False
        self.halted = True
        self.fault: str | None = None
        self.instruction_count = 0
        self.last_mnemonic = "HALT"
        self.alu_digit_cycles = 0
        self.last_bcd_carry = 0
        self.channel_input: deque[int] = deque()
        self.channel_output: list[int] = []

    def ensure_account(self, name: str) -> int:
        name = name.upper()
        if name in self.account_addresses:
            return self.account_addresses[name]
        if len(self.account_addresses) >= ACCOUNT_CAPACITY:
            raise CPUFault(f"no decimal memory word reserved for account {name}")
        address = ACCOUNT_START + ACCOUNT_STRIDE * len(self.account_addresses)
        self.account_addresses[name] = address
        self.write_field(address, 0)
        return address

    def account_balances(self) -> dict[str, int]:
        return {name: self.read_field(address) for name, address in self.account_addresses.items()}

    def write_field(self, address: int, value: int) -> None:
        if not 0 <= address < MEMORY_SIZE:
            raise CPUFault(f"field address {address} is outside memory")
        magnitude = abs(int(value))
        digits = str(magnitude)
        if len(digits) > FIELD_WIDTH:
            raise CPUFault(f"signed decimal value exceeds {FIELD_WIDTH} digits")
        end = address + len(digits)
        if end >= MEMORY_SIZE:
            raise CPUFault("decimal field crosses the end of memory")
        for offset, digit in enumerate(digits):
            value_byte = int(digit) | (WORD_MARK if offset == 0 else 0)
            if offset == 0 and value < 0:
                value_byte |= NEGATIVE
            self.memory[address + offset] = value_byte
        self.memory[end] = GROUP_MARK

    def read_field(self, address: int) -> int:
        if not 0 <= address < MEMORY_SIZE or not (self.memory[address] & WORD_MARK):
            raise CPUFault(f"no word mark at decimal field address {address}")
        value = 0
        count = 0
        negative = bool(self.memory[address] & NEGATIVE)
        for offset in range(FIELD_WIDTH):
            location = address + offset
            if location >= MEMORY_SIZE:
                break
            cell = self.memory[location]
            if offset and cell & WORD_MARK:
                break
            character = cell & 0x0F
            if character == GROUP_MARK:
                break
            if character > 9:
                raise CPUFault(f"non-decimal character {character:x} in numeric word")
            value = value * 10 + character
            count += 1
        if not count:
            raise CPUFault(f"empty numeric word at address {address}")
        return -value if negative else value

    def examine(self, address: int) -> MemoryCell:
        if not 0 <= address < MEMORY_SIZE:
            raise CPUFault("examine address is outside memory")
        cell = self.memory[address]
        return MemoryCell(cell & 0x0F, bool(cell & WORD_MARK), bool(cell & NEGATIVE))

    def deposit_scratch(self, address: int, character: int) -> None:
        """Deposit a character only in the panel's reserved diagnostic cells."""
        if not PANEL_SCRATCH_START <= address < MEMORY_SIZE:
            raise CPUFault(f"deposit is limited to scratch cells {PANEL_SCRATCH_START}..255")
        if not 0 <= character <= 0x0F:
            raise CPUFault("memory character must fit in one nibble")
        self.memory[address] = character

    def load_program(self, instructions: list[tuple[str, int]]) -> None:
        if len(instructions) * 4 > ACCOUNT_START:
            raise CPUFault("program overlaps the reserved account words")
        self.memory[:ACCOUNT_START] = bytes(ACCOUNT_START)
        pc = 0
        for mnemonic, address in instructions:
            name = mnemonic.upper()
            if name not in OPCODES:
                raise CPUFault(f"unknown instruction {mnemonic}")
            if not 0 <= address < MEMORY_SIZE:
                raise CPUFault("instruction address operand is outside memory")
            opcode = OPCODES[name]
            address_digits = f"{address:03d}"
            self.memory[pc] = WORD_MARK | opcode
            for offset, digit in enumerate(address_digits, start=1):
                self.memory[pc + offset] = int(digit)
            pc += 4
        self.pc = 0
        self.ir = 0
        self.ar = 0
        self.halted = False
        self.fault = None

    def _set_flags(self, value: int) -> None:
        self.zero_flag = value == 0
        self.negative_flag = value < 0

    def _step(self) -> None:
        if self.pc > MEMORY_SIZE - 4 or not (self.memory[self.pc] & WORD_MARK):
            raise CPUFault(f"instruction word mark missing at PC {self.pc}")
        opcode = self.memory[self.pc] & 0x0F
        address_digits = [self.memory[self.pc + i] & 0x0F for i in (1, 2, 3)]
        if any(digit > 9 for digit in address_digits):
            raise CPUFault(f"invalid decimal address at PC {self.pc}")
        address = address_digits[0] * 100 + address_digits[1] * 10 + address_digits[2]
        if address >= MEMORY_SIZE:
            raise CPUFault(f"instruction address {address} is outside memory")
        self.ir = opcode
        if opcode != OPCODES["HALT"]:
            self.ar = address
        self.pc += 4
        self.last_mnemonic = MNEMONICS.get(opcode, "INVALID")

        if opcode == OPCODES["HALT"]:
            self.halted = True
        elif opcode == OPCODES["LDA"]:
            self.accumulator = self.read_field(address)
            self._set_flags(self.accumulator)
        elif opcode == OPCODES["STA"]:
            self.write_field(address, self.accumulator)
        elif opcode == OPCODES["ADD"]:
            self._alu_add(self.read_field(address))
        elif opcode == OPCODES["SUB"]:
            self._alu_add(-self.read_field(address))
        elif opcode == OPCODES["JMP"]:
            self.pc = address
        elif opcode == OPCODES["JZ"]:
            if self.zero_flag:
                self.pc = address
        elif opcode == OPCODES["JN"]:
            if self.negative_flag:
                self.pc = address
        elif opcode == OPCODES["IN"]:
            if not self.channel_input:
                raise CPUFault("input channel is empty")
            self.accumulator = self.channel_input.popleft()
            self._check_accumulator()
        elif opcode == OPCODES["OUT"]:
            self.channel_output.append(self.accumulator)
        elif opcode == OPCODES["CMP"]:
            self._set_flags(self.accumulator - self.read_field(address))
        elif opcode == OPCODES["NOP"]:
            pass
        else:
            raise CPUFault(f"unsupported opcode {opcode:x}")
        self.instruction_count += 1

    def _check_accumulator(self) -> None:
        if abs(self.accumulator) >= 10**FIELD_WIDTH:
            self.overflow_flag = True
            raise CPUFault("decimal accumulator overflow")
        self.overflow_flag = False
        self._set_flags(self.accumulator)

    def _alu_add(self, operand: int) -> None:
        """Add signed decimal words one BCD digit per modeled micro-cycle."""
        left = abs(self.accumulator)
        right = abs(operand)
        left_negative = self.accumulator < 0
        right_negative = operand < 0
        self.alu_digit_cycles += FIELD_WIDTH
        if left_negative == right_negative:
            carry = 0
            result = 0
            place = 1
            for _ in range(FIELD_WIDTH):
                digit = (left % 10) + (right % 10) + carry
                left //= 10
                right //= 10
                if digit >= 10:
                    digit -= 10
                    carry = 1
                else:
                    carry = 0
                result += digit * place
                place *= 10
            self.last_bcd_carry = carry
            self.carry_flag = bool(carry)
            if carry:
                self.overflow_flag = True
                raise CPUFault("decimal accumulator overflow")
            self.accumulator = -result if left_negative and result else result
        else:
            minuend, subtrahend = (left, right) if left >= right else (right, left)
            result = 0
            place = 1
            borrow = 0
            for _ in range(FIELD_WIDTH):
                digit = (minuend % 10) - (subtrahend % 10) - borrow
                minuend //= 10
                subtrahend //= 10
                if digit < 0:
                    digit += 10
                    borrow = 1
                else:
                    borrow = 0
                result += digit * place
                place *= 10
            self.last_bcd_carry = 0
            self.carry_flag = not bool(borrow)
            sign = left_negative if left >= right else right_negative
            self.accumulator = -result if sign and result else result
        self.overflow_flag = False
        self._set_flags(self.accumulator)

    def run(self, max_instructions: int = 1024) -> int:
        executed = 0
        try:
            while not self.halted and executed < max_instructions:
                self._step()
                executed += 1
        except CPUFault as exc:
            self.fault = str(exc)
            raise
        if not self.halted:
            self.fault = "instruction budget exhausted"
            raise CPUFault(self.fault)
        return executed

    def transfer(self, source: str, destination: str, amount: int) -> None:
        """Run debit and credit instruction sequences atomically on a clone."""
        if amount < 0:
            raise CPUFault("transfer amount must be non-negative")
        trial = copy.deepcopy(self)
        source_address = trial.ensure_account(source)
        destination_address = trial.ensure_account(destination)
        if source_address == destination_address:
            raise CPUFault("decimal transfer source and destination are identical")
        trial.write_field(AMOUNT_ADDRESS, amount)
        trial.load_program(
            [("LDA", source_address), ("SUB", AMOUNT_ADDRESS), ("STA", source_address), ("HALT", 0)]
        )
        trial.run()
        trial.load_program(
            [("LDA", destination_address), ("ADD", AMOUNT_ADDRESS), ("STA", destination_address), ("HALT", 0)]
        )
        trial.run()
        self.__dict__.update(trial.__dict__)

    def preview_transfer(self, source: str, destination: str, amount: int) -> dict[str, int]:
        """Check whether a transfer fits the reference CPU without mutating it."""
        trial = copy.deepcopy(self)
        trial.transfer(source, destination, amount)
        return trial.account_balances()
