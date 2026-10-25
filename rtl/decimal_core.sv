// Preliminary synthesizable, character-addressed decimal CPU.
// This is an original compact ISA, not IBM 1401 binary compatibility.
module decimal_core (
    input  logic        clk,
    input  logic        reset_n,
    input  logic        run,
    input  logic        single_step,
    input  logic        halt_request,
    input  logic        deposit_enable,
    input  logic [7:0]  deposit_address,
    input  logic [7:0]  deposit_cell,
    input  logic [7:0]  examine_address,
    output logic [7:0]  examine_cell,
    input  logic        channel_in_valid,
    input  logic [47:0] channel_in_bcd,
    input  logic        channel_in_negative,
    output logic        channel_in_ready,
    output logic        channel_out_valid,
    output logic [47:0] channel_out_bcd,
    output logic        channel_out_negative,
    output logic [7:0]  pc_o,
    output logic [7:0]  ar_o,
    output logic [3:0]  ir_o,
    output logic [47:0] ac_bcd_o,
    output logic        ac_negative_o,
    output logic        zero_o,
    output logic        negative_o,
    output logic        carry_o,
    output logic        overflow_o,
    output logic        halted_o,
    output logic        fault_o,
    output logic [31:0] instruction_count_o,
    output logic [31:0] alu_digit_cycles_o
);
    localparam logic [3:0] OP_HALT = 4'h0;
    localparam logic [3:0] OP_LDA  = 4'h1;
    localparam logic [3:0] OP_STA  = 4'h2;
    localparam logic [3:0] OP_ADD  = 4'h3;
    localparam logic [3:0] OP_SUB  = 4'h4;
    localparam logic [3:0] OP_JMP  = 4'h5;
    localparam logic [3:0] OP_JZ   = 4'h6;
    localparam logic [3:0] OP_JN   = 4'h7;
    localparam logic [3:0] OP_IN   = 4'h8;
    localparam logic [3:0] OP_OUT  = 4'h9;
    localparam logic [3:0] OP_CMP  = 4'hA;
    localparam logic [3:0] OP_NOP  = 4'hB;
    localparam logic [3:0] GROUP_MARK = 4'hC;

    typedef enum logic [3:0] {
        S_FETCH, S_DECODE, S_SCAN, S_LOAD, S_EXEC, S_ALU,
        S_STORE, S_CHANNEL, S_HALTED, S_FAULT
    } state_t;

    logic [7:0] memory [0:255];
    state_t state;
    logic [7:0] pc, ar;
    logic [3:0] ir;
    logic [47:0] ac_bcd, operand_bcd;
    logic ac_negative, operand_negative;
    logic zero_flag, negative_flag, carry_flag, overflow_flag;
    logic [47:0] alu_left_bcd, alu_right_bcd, alu_work_bcd;
    logic [3:0] alu_digit_index;
    logic alu_subtract_mode, alu_result_negative, alu_carry_bit, alu_borrow_bit;
    logic compare_mode;
    logic [3:0] scan_index, field_length, load_index, store_index;
    logic [31:0] instruction_count, alu_digit_cycles;
    logic [7:0] cell_value;
    integer i;
    integer decoded_address;
    integer scan_address;
    integer load_address;
    integer digit_result;
    logic [4:0] digit_sum;
    logic signed [5:0] digit_difference;
    logic next_carry, next_borrow, effective_right_negative;
    logic [3:0] final_digit;
    logic [47:0] assembled_alu;

    assign examine_cell = memory[examine_address];
    assign pc_o = pc;
    assign ar_o = ar;
    assign ir_o = ir;
    assign ac_bcd_o = ac_bcd;
    assign ac_negative_o = ac_negative;
    assign zero_o = zero_flag;
    assign negative_o = negative_flag;
    assign carry_o = carry_flag;
    assign overflow_o = overflow_flag;
    assign instruction_count_o = instruction_count;
    assign alu_digit_cycles_o = alu_digit_cycles;
    assign channel_in_ready = (state == S_CHANNEL) && (ir == OP_IN);

    // Signed magnitude is selected in S_EXEC; S_ALU performs one BCD digit per clock.

    always_ff @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            for (i = 0; i < 256; i = i + 1) memory[i] <= 8'b0;
            state <= S_HALTED;
            pc <= 8'b0;
            ar <= 8'b0;
            ir <= OP_HALT;
            ac_bcd <= 48'b0;
            operand_bcd <= 48'b0;
            ac_negative <= 1'b0;
            operand_negative <= 1'b0;
            zero_flag <= 1'b1;
            negative_flag <= 1'b0;
            carry_flag <= 1'b0;
            overflow_flag <= 1'b0;
            alu_left_bcd <= 48'b0;
            alu_right_bcd <= 48'b0;
            alu_work_bcd <= 48'b0;
            alu_digit_index <= 4'b0;
            alu_subtract_mode <= 1'b0;
            alu_result_negative <= 1'b0;
            alu_carry_bit <= 1'b0;
            alu_borrow_bit <= 1'b0;
            compare_mode <= 1'b0;
            scan_index <= 4'b0;
            field_length <= 4'b0;
            load_index <= 4'b0;
            store_index <= 4'b0;
            instruction_count <= 32'b0;
            alu_digit_cycles <= 32'b0;
            channel_out_valid <= 1'b0;
            channel_out_bcd <= 48'b0;
            channel_out_negative <= 1'b0;
            halted_o <= 1'b1;
            fault_o <= 1'b0;
            decoded_address = 0;
            scan_address = 0;
            load_address = 0;
            digit_result = 0;
            digit_sum = 0;
            digit_difference = 0;
            next_carry = 0;
            next_borrow = 0;
            effective_right_negative = 0;
            final_digit = 0;
            assembled_alu = 0;
            cell_value = 0;
        end else begin
            channel_out_valid <= 1'b0;
            if (deposit_enable && halted_o && deposit_address >= 8'd249)
                memory[deposit_address] <= deposit_cell;
            if (halt_request) begin
                state <= S_HALTED;
                halted_o <= 1'b1;
            end else if (run || single_step) begin
                if (state == S_HALTED) begin
                    state <= S_FETCH;
                    halted_o <= 1'b0;
                end else if (state == S_FAULT) begin
                    halted_o <= 1'b1;
                end else begin
                    case (state)
                        S_FETCH: begin
                            if (pc > 252 || !memory[pc][7]) begin
                                fault_o <= 1'b1;
                                state <= S_FAULT;
                                halted_o <= 1'b1;
                            end else begin
                                ir <= memory[pc][3:0];
                                state <= S_DECODE;
                            end
                        end
                        S_DECODE: begin
                            decoded_address = memory[pc+1][3:0] * 100 + memory[pc+2][3:0] * 10 + memory[pc+3][3:0];
                            if (memory[pc+1][3:0] > 9 || memory[pc+2][3:0] > 9 || memory[pc+3][3:0] > 9 || decoded_address > 255) begin
                                fault_o <= 1'b1;
                                state <= S_FAULT;
                                halted_o <= 1'b1;
                            end else begin
                                if (ir != OP_HALT) ar <= decoded_address[7:0];
                                pc <= pc + 4;
                                case (ir)
                                    OP_HALT: begin
                                        state <= S_HALTED;
                                        halted_o <= 1'b1;
                                        instruction_count <= instruction_count + 1;
                                    end
                                    OP_LDA, OP_ADD, OP_SUB, OP_CMP: begin
                                        scan_index <= 0;
                                        field_length <= 0;
                                        state <= S_SCAN;
                                    end
                                    OP_STA: begin
                                        if (decoded_address > 243) begin
                                            fault_o <= 1'b1;
                                            state <= S_FAULT;
                                            halted_o <= 1'b1;
                                        end else begin
                                            store_index <= 0;
                                            state <= S_STORE;
                                        end
                                    end
                                    OP_JMP: begin
                                        pc <= decoded_address[7:0];
                                        state <= S_FETCH;
                                        instruction_count <= instruction_count + 1;
                                    end
                                    OP_JZ: begin
                                        if (zero_flag) pc <= decoded_address[7:0];
                                        state <= S_FETCH;
                                        instruction_count <= instruction_count + 1;
                                    end
                                    OP_JN: begin
                                        if (negative_flag) pc <= decoded_address[7:0];
                                        state <= S_FETCH;
                                        instruction_count <= instruction_count + 1;
                                    end
                                    OP_IN: state <= S_CHANNEL;
                                    OP_OUT: begin
                                        channel_out_bcd <= ac_bcd;
                                        channel_out_negative <= ac_negative;
                                        channel_out_valid <= 1'b1;
                                        state <= S_FETCH;
                                        instruction_count <= instruction_count + 1;
                                    end
                                    OP_NOP: begin
                                        state <= S_FETCH;
                                        instruction_count <= instruction_count + 1;
                                    end
                                    default: begin
                                        fault_o <= 1'b1;
                                        state <= S_FAULT;
                                        halted_o <= 1'b1;
                                    end
                                endcase
                            end
                        end
                        S_SCAN: begin
                            scan_address = ar + scan_index;
                            if (scan_address >= 256) begin
                                fault_o <= 1'b1;
                                state <= S_FAULT;
                                halted_o <= 1'b1;
                            end else if (scan_index == 0 && !memory[ar][7]) begin
                                fault_o <= 1'b1;
                                state <= S_FAULT;
                                halted_o <= 1'b1;
                            end else if (scan_index != 0 && memory[scan_address][7]) begin
                                field_length <= scan_index;
                                load_index <= 0;
                                operand_bcd <= 48'b0;
                                state <= S_LOAD;
                            end else if (memory[scan_address][3:0] == GROUP_MARK) begin
                                if (scan_index == 0) begin
                                    fault_o <= 1'b1;
                                    state <= S_FAULT;
                                    halted_o <= 1'b1;
                                end else begin
                                    field_length <= scan_index;
                                    load_index <= 0;
                                    operand_bcd <= 48'b0;
                                    state <= S_LOAD;
                                end
                            end else if (scan_index >= 12 || memory[scan_address][3:0] > 9) begin
                                fault_o <= 1'b1;
                                state <= S_FAULT;
                                halted_o <= 1'b1;
                            end else begin
                                scan_index <= scan_index + 1;
                            end
                        end
                        S_LOAD: begin
                            if (load_index < field_length) begin
                                load_address = ar + field_length - 1 - load_index;
                                operand_bcd[load_index*4 +: 4] <= memory[load_address][3:0];
                            end else begin
                                operand_bcd[load_index*4 +: 4] <= 4'b0;
                            end
                            if (load_index == 11) begin
                                operand_negative <= memory[ar][4];
                                state <= S_EXEC;
                            end else begin
                                load_index <= load_index + 1;
                            end
                        end
                        S_EXEC: begin
                            if (ir == OP_LDA) begin
                                ac_bcd <= operand_bcd;
                                ac_negative <= operand_negative && (operand_bcd != 48'b0);
                                zero_flag <= operand_bcd == 48'b0;
                                negative_flag <= operand_negative && (operand_bcd != 48'b0);
                                carry_flag <= 1'b0;
                                overflow_flag <= 1'b0;
                                instruction_count <= instruction_count + 1;
                                state <= S_FETCH;
                            end else begin
                                compare_mode <= (ir == OP_CMP);
                                effective_right_negative = operand_negative;
                                if (ir == OP_SUB || ir == OP_CMP)
                                    effective_right_negative = ~operand_negative;
                                if (ac_negative == effective_right_negative) begin
                                    alu_left_bcd <= ac_bcd;
                                    alu_right_bcd <= operand_bcd;
                                    alu_subtract_mode <= 1'b0;
                                    alu_result_negative <= ac_negative;
                                end else if (ac_bcd >= operand_bcd) begin
                                    alu_left_bcd <= ac_bcd;
                                    alu_right_bcd <= operand_bcd;
                                    alu_subtract_mode <= 1'b1;
                                    alu_result_negative <= ac_negative;
                                end else begin
                                    alu_left_bcd <= operand_bcd;
                                    alu_right_bcd <= ac_bcd;
                                    alu_subtract_mode <= 1'b1;
                                    alu_result_negative <= effective_right_negative;
                                end
                                alu_work_bcd <= 48'b0;
                                alu_digit_index <= 0;
                                alu_carry_bit <= 1'b0;
                                alu_borrow_bit <= 1'b0;
                                state <= S_ALU;
                            end
                        end
                        S_ALU: begin
                            alu_digit_cycles <= alu_digit_cycles + 1;
                            next_carry = alu_carry_bit;
                            next_borrow = alu_borrow_bit;
                            if (alu_subtract_mode) begin
                                digit_difference = $signed({2'b00, alu_left_bcd[alu_digit_index*4 +: 4]})
                                    - $signed({2'b00, alu_right_bcd[alu_digit_index*4 +: 4]})
                                    - $signed({5'b0, alu_borrow_bit});
                                if (digit_difference < 0) begin
                                    digit_difference = digit_difference + 10;
                                    next_borrow = 1'b1;
                                end else begin
                                    next_borrow = 1'b0;
                                end
                                final_digit = digit_difference[3:0];
                            end else begin
                                digit_sum = {1'b0, alu_left_bcd[alu_digit_index*4 +: 4]}
                                    + {1'b0, alu_right_bcd[alu_digit_index*4 +: 4]} + alu_carry_bit;
                                if (digit_sum >= 10) begin
                                    digit_sum = digit_sum - 10;
                                    next_carry = 1'b1;
                                end else begin
                                    next_carry = 1'b0;
                                end
                                final_digit = digit_sum[3:0];
                            end
                            alu_work_bcd[alu_digit_index*4 +: 4] <= final_digit;
                            if (alu_digit_index == 11) begin
                                assembled_alu = alu_work_bcd;
                                assembled_alu[alu_digit_index*4 +: 4] = final_digit;
                                carry_flag <= alu_subtract_mode ? ~next_borrow : next_carry;
                                overflow_flag <= !alu_subtract_mode && next_carry;
                                if (!alu_subtract_mode && next_carry) begin
                                    fault_o <= 1'b1;
                                    state <= S_FAULT;
                                    halted_o <= 1'b1;
                                end else begin
                                    zero_flag <= assembled_alu == 48'b0;
                                    negative_flag <= alu_result_negative && (assembled_alu != 48'b0);
                                    if (!compare_mode) begin
                                        ac_bcd <= assembled_alu;
                                        ac_negative <= alu_result_negative && (assembled_alu != 48'b0);
                                    end
                                    instruction_count <= instruction_count + 1;
                                    state <= S_FETCH;
                                end
                            end else begin
                                alu_digit_index <= alu_digit_index + 1;
                                alu_carry_bit <= next_carry;
                                alu_borrow_bit <= next_borrow;
                            end
                        end
                        S_STORE: begin
                            memory[ar + store_index] <= ((store_index == 0) ? 8'h80 : 8'h00)
                                | ((store_index == 0 && ac_negative) ? 8'h10 : 8'h00)
                                | {4'b0, ac_bcd[(11-store_index)*4 +: 4]};
                            if (store_index == 11) begin
                                memory[ar + 12] <= {4'b0, GROUP_MARK};
                                instruction_count <= instruction_count + 1;
                                state <= S_FETCH;
                            end else begin
                                store_index <= store_index + 1;
                            end
                        end
                        S_CHANNEL: begin
                            if (channel_in_valid) begin
                                ac_bcd <= channel_in_bcd;
                                ac_negative <= channel_in_negative && (channel_in_bcd != 48'b0);
                                zero_flag <= channel_in_bcd == 48'b0;
                                negative_flag <= channel_in_negative && (channel_in_bcd != 48'b0);
                                instruction_count <= instruction_count + 1;
                                state <= S_FETCH;
                            end
                        end
                        default: begin
                            fault_o <= 1'b1;
                            state <= S_FAULT;
                            halted_o <= 1'b1;
                        end
                    endcase
                end
            end
        end
    end
endmodule
