module decimal_core_tb;
    logic clk = 1'b0;
    logic reset_n = 1'b0;
    logic run = 1'b0;
    logic single_step = 1'b0;
    logic halt_request = 1'b0;
    logic deposit_enable = 1'b0;
    logic [7:0] deposit_address = 0;
    logic [7:0] deposit_cell = 0;
    logic [7:0] examine_address = 0;
    logic [7:0] examine_cell;
    logic channel_in_valid = 1'b0;
    logic [47:0] channel_in_bcd = 0;
    logic channel_in_negative = 1'b0;
    logic channel_in_ready;
    logic channel_out_valid;
    logic [47:0] channel_out_bcd;
    logic channel_out_negative;
    logic [7:0] pc;
    logic [7:0] ar;
    logic [3:0] ir;
    logic [47:0] ac_bcd;
    logic ac_negative;
    logic zero_flag, negative_flag, carry_flag, overflow_flag, halted, fault;
    logic [31:0] instruction_count, alu_digit_cycles;
    integer source_balance;
    integer destination_balance;
    integer amount_minor;
    integer expected_source;
    integer expected_destination;
    integer source_result;
    integer destination_result;
    integer timeout_count;
    integer digit;
    integer magnitude;
    integer index;

    always #5 clk = ~clk;

    decimal_core dut (
        .clk(clk), .reset_n(reset_n), .run(run), .single_step(single_step),
        .halt_request(halt_request), .deposit_enable(deposit_enable),
        .deposit_address(deposit_address), .deposit_cell(deposit_cell),
        .examine_address(examine_address), .examine_cell(examine_cell),
        .channel_in_valid(channel_in_valid), .channel_in_bcd(channel_in_bcd),
        .channel_in_negative(channel_in_negative), .channel_in_ready(channel_in_ready),
        .channel_out_valid(channel_out_valid), .channel_out_bcd(channel_out_bcd),
        .channel_out_negative(channel_out_negative), .pc_o(pc), .ar_o(ar), .ir_o(ir),
        .ac_bcd_o(ac_bcd), .ac_negative_o(ac_negative), .zero_o(zero_flag),
        .negative_o(negative_flag), .carry_o(carry_flag), .overflow_o(overflow_flag),
        .halted_o(halted), .fault_o(fault), .instruction_count_o(instruction_count),
        .alu_digit_cycles_o(alu_digit_cycles)
    );

    task automatic write_field(input integer address, input integer signed value);
        integer remaining;
        integer offset;
        begin
            remaining = value < 0 ? -value : value;
            for (offset = 11; offset >= 0; offset = offset - 1) begin
                digit = remaining % 10;
                remaining = remaining / 10;
                dut.memory[address + offset] = digit[3:0];
                if (offset == 11) begin
                    dut.memory[address + offset][7] = 1'b1;
                    dut.memory[address + offset][4] = value < 0;
                end
            end
            dut.memory[address + 12] = 8'h0C;
        end
    endtask

    task automatic write_instruction(input integer address, input logic [3:0] opcode, input integer operand);
        begin
            dut.memory[address] = 8'h80 | {4'b0, opcode};
            dut.memory[address + 1] = ((operand / 100) % 10);
            dut.memory[address + 2] = ((operand / 10) % 10);
            dut.memory[address + 3] = (operand % 10);
        end
    endtask

    function automatic integer read_field(input integer address);
        integer value;
        integer count;
        integer offset;
        integer char_code;
        begin
            value = 0;
            count = 0;
            for (offset = 0; offset < 12; offset = offset + 1) begin
                char_code = dut.memory[address + offset][3:0];
                if (char_code != 12 && count < 12) begin
                    value = value * 10 + char_code;
                    count = count + 1;
                end
            end
            if (dut.memory[address][4]) value = -value;
            read_field = value;
        end
    endfunction

    initial begin
        source_balance = 42500;
        destination_balance = -12500;
        amount_minor = 4275;
        if (!$value$plusargs("SRC=%d", source_balance)) source_balance = 42500;
        if (!$value$plusargs("DST=%d", destination_balance)) destination_balance = -12500;
        if (!$value$plusargs("AMOUNT=%d", amount_minor)) amount_minor = 4275;
        expected_source = source_balance - amount_minor;
        expected_destination = destination_balance + amount_minor;

        repeat (2) @(posedge clk);
        #1 reset_n = 1'b1;
        @(negedge clk);

        // Program: LDA source; SUB amount; STA source; LDA destination;
        // ADD amount; STA destination; HALT.
        write_instruction(0, 4'h1, 100);
        write_instruction(4, 4'h4, 120);
        write_instruction(8, 4'h2, 100);
        write_instruction(12, 4'h1, 140);
        write_instruction(16, 4'h3, 120);
        write_instruction(20, 4'h2, 140);
        write_instruction(24, 4'h0, 0);
        write_field(100, source_balance);
        write_field(120, amount_minor);
        write_field(140, destination_balance);

        @(negedge clk);
        run = 1'b1;
        wait (halted == 1'b0);
        wait (halted == 1'b1 || fault == 1'b1);
        run = 1'b0;
        #1;
        source_result = read_field(100);
        destination_result = read_field(140);
        if (fault) $fatal(1, "RTL fault at PC %0d", pc);
        if (source_result != expected_source || destination_result != expected_destination)
            $fatal(1, "mismatch: source %0d/%0d destination %0d/%0d", source_result, expected_source, destination_result, expected_destination);
        if (instruction_count != 7 || alu_digit_cycles != 24)
            $fatal(1, "unexpected cycle evidence: instructions=%0d alu_digits=%0d", instruction_count, alu_digit_cycles);
        $display("RESULT %0d %0d %0d %0d %0d", source_result, destination_result, ac_negative, instruction_count, alu_digit_cycles);
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "simulation timeout");
    end
endmodule
