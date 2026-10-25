# Decimal panel and FPGA scaffold

The panel contract is board-neutral. `rtl/panel_connector.sv` maps processor
register and position values to BCD lamps, the word-mark window, status lamps,
a signed meter input, and the red beacon. The beacon is driven only by
`reconciliation_break_minor != 0`.

`rtl/decimal_core.sv` is a synthesizable-oriented starter for the original
character-addressed ISA: 256 byte cells, word marks, signed variable-length
BCD fields, an accumulator, branches, channels, examine, halt and deposit. The
deposit gate accepts only the reserved diagnostic cells 249–255 while halted.
It is not IBM 1401 compatible. The Python `ReferenceCPU` remains the runnable
conformance oracle and ledger uses it to perform its double-entry transfers.

The browser `/panel` page shows modeled register digits, flags, word marks,
member-position meter input, key position and the reconciliation signal.
Controls change the simulated key or selector, examine memory, or write only
scratch cells. No panel action can post or alter a member position.

The RTL testbench at `rtl/tb/decimal_core_tb.sv` describes a double-entry
transfer vector. Board pin maps, electrical drivers, enclosure dimensions,
moving-coil calibration and physical printer timing remain board-specific and
have not been selected. No FPGA synthesis, timing closure, pin mapping or
physical stack validation is claimed.
