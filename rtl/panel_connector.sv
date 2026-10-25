// Board-neutral signal contract for the physical decimal panel.
// Pin assignments and electrical drivers are intentionally board-specific.
module panel_connector (
    input  logic [2:0]  register_select, // 0 AC, 1 PC, 2 AR, 3 IR, 4 member position
    input  logic [47:0] ac_bcd,
    input  logic        ac_negative,
    input  logic [7:0]  pc,
    input  logic [7:0]  ar,
    input  logic [3:0]  ir,
    input  logic [47:0] member_position_bcd,
    input  logic        zero_flag,
    input  logic        negative_flag,
    input  logic        carry_flag,
    input  logic        overflow_flag,
    input  logic [15:0] wordmark_window,
    input  logic signed [23:0] member_position_minor,
    input  logic signed [23:0] reconciliation_break_minor,
    input  logic [3:0]  day_key_feedback,
    output logic [47:0] bcd_digit_lamps,
    output logic        sign_lamp,
    output logic [15:0] wordmark_lamps,
    output logic [6:0]  status_lamps,
    output logic signed [23:0] liquidity_meter_input,
    output logic        red_beacon
);
    function automatic [47:0] binary_to_bcd(input logic [7:0] value);
        logic [47:0] packed;
        integer remaining;
        integer index;
        begin
            packed = 48'b0;
            remaining = value;
            for (index = 0; index < 12; index = index + 1) begin
                packed[index*4 +: 4] = remaining % 10;
                remaining = remaining / 10;
            end
            binary_to_bcd = packed;
        end
    endfunction

    always_comb begin
        bcd_digit_lamps = ac_bcd;
        sign_lamp = ac_negative;
        case (register_select)
            3'd1: begin bcd_digit_lamps = binary_to_bcd(pc); sign_lamp = 1'b0; end
            3'd2: begin bcd_digit_lamps = binary_to_bcd(ar); sign_lamp = 1'b0; end
            3'd3: begin bcd_digit_lamps = binary_to_bcd({4'b0, ir}); sign_lamp = 1'b0; end
            3'd4: begin bcd_digit_lamps = member_position_bcd; sign_lamp = member_position_minor < 0; end
            default: begin bcd_digit_lamps = ac_bcd; sign_lamp = ac_negative; end
        endcase
        wordmark_lamps = wordmark_window;
        status_lamps = {day_key_feedback[2:0], overflow_flag, carry_flag, negative_flag, zero_flag};
        liquidity_meter_input = member_position_minor;
        red_beacon = (reconciliation_break_minor != 0);
    end
endmodule
