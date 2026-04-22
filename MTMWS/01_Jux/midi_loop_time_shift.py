import board
import analogio
import digitalio
import pwmio
import time
import usb_midi
import adafruit_midi
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff

# --- HELPER FUNCTION: TIMELINE SCANNER ---
# This checks if a playhead crossed a note's timestamp during the last microscopic frame
def get_events_in_window(start_t, end_t, events, duration):
    triggers = []
    if start_t < end_t:
        for t, p, v in events:
            if start_t < t <= end_t:
                triggers.append((p, v))
    else:
        # Playhead wrapped around to the beginning of the loop
        for t, p, v in events:
            if start_t < t <= duration:
                triggers.append((p, v))
            if 0 <= t <= end_t:
                triggers.append((p, v))
    return triggers

# --- 1. HARDWARE SETUP ---
cv1_pitch_out = pwmio.PWMOut(board.CV1, frequency=100000, duty_cycle=0)
cv2_vel_out = pwmio.PWMOut(board.CV2, frequency=100000, duty_cycle=0)
gate1_out = digitalio.DigitalInOut(board.GATE1)
gate1_out.direction = digitalio.Direction.OUTPUT

cv3_pitch_out = pwmio.PWMOut(board.CV3, frequency=100000, duty_cycle=0)
cv4_vel_out = pwmio.PWMOut(board.CV4, frequency=100000, duty_cycle=0)
gate2_out = digitalio.DigitalInOut(board.GATE2)
gate2_out.direction = digitalio.Direction.OUTPUT

pot_x = analogio.AnalogIn(board.POT_1)      # N-Notes Knob
pot_big = analogio.AnalogIn(board.POT_2)    # Time Shift Knob

switch_down = digitalio.DigitalInOut(board.SW_DOWN)
switch_down.direction = digitalio.Direction.INPUT
switch_down.pull = digitalio.Pull.UP 

midi = adafruit_midi.MIDI(midi_in=usb_midi.ports[0])

# --- 2. LOOPER VARIABLES ---
MAX_BUFFER = 30
note_buffer = []  

was_in_loop_mode = False
last_n_notes = 0

# Timeline variables
loop_events = []
loop_duration = 0.1
max_advance = 0.0
curr_t_ch1 = 0.0
last_update_time = 0.0

last_live_note_time = 0
GATE_LENGTH = 0.05    
gate1_opened_at = 0
gate2_opened_at = 0

print("Advanced Time-Shift Looper ready!")

while True:
    n_notes = int((pot_x.value / 65535) * 29) + 1 
    loop_mode_active = not switch_down.value
    now = time.monotonic()

    if loop_mode_active:
        # ==========================================
        # LOOP MODE: Dual Playheads with Time Shift
        # ==========================================
        
        # If we just entered loop mode, OR if you turned the N-Notes knob, rebuild the timeline!
        if not was_in_loop_mode or n_notes != last_n_notes:
            was_in_loop_mode = True
            last_n_notes = n_notes
            
            # Build Absolute Timeline
            current_sequence = note_buffer[-n_notes:] if note_buffer else []
            loop_events = []
            current_t = 0.0
            
            for d, p, v in current_sequence:
                current_t += d
                loop_events.append((current_t, p, v))
                
            loop_duration = current_t if current_t > 0 else 0.1
            
            # Calculate exact time needed to advance CH2 by 1 note (Delta of Note 2)
            if len(current_sequence) > 1:
                max_advance = current_sequence[1][0] 
            else:
                max_advance = 0.0
                
            # Place playhead exactly on the first note so it plays instantly on press
            curr_t_ch1 = loop_events[0][0] if loop_events else 0.0
            last_update_time = now
            
            # Simulate a microscopic time-step so it triggers on the very first frame
            virtual_last_t_ch1 = (curr_t_ch1 - 0.001) % loop_duration
            dt = 0.001 
            
        else:
            # Advance time normally
            dt = now - last_update_time
            last_update_time = now
            
            virtual_last_t_ch1 = curr_t_ch1
            curr_t_ch1 = (curr_t_ch1 + dt) % loop_duration
            
        if len(loop_events) > 0:
            
            # --- PROCESS CHANNEL 1 ---
            ch1_triggers = get_events_in_window(virtual_last_t_ch1, curr_t_ch1, loop_events, loop_duration)
            if ch1_triggers:
                p, v = ch1_triggers[-1]
                cv1_pitch_out.duty_cycle = int((p / 127) * 65535)
                cv2_vel_out.duty_cycle = int((v / 127) * 65535)
                gate1_out.value = True
                gate1_opened_at = last_update_time
                
            # --- CALCULATE BIG KNOB OFFSET ---
            pot2_val = pot_big.value
            
            if pot2_val < 25000:
                # 7 to 11 o'clock: Local Offset (Advancing CH2 playhead)
                # Scales from max_advance (fully down) to 0 (11 o'clock)
                advance_factor = (25000 - pot2_val) / 25000.0
                ch2_time_shift = advance_factor * max_advance
                
            elif pot2_val > 40000:
                # 1 to 5 o'clock: Global Delay (Delaying CH2 playhead)
                # Scales from 0 (1 o'clock) to 1.0 seconds (fully up)
                delay_factor = (pot2_val - 40000) / 25535.0
                ch2_time_shift = - (delay_factor * 1.0) 
                
            else:
                # 11 to 1 o'clock: Deadzone / Overlap
                ch2_time_shift = 0.0
                
            # --- PROCESS CHANNEL 2 ---
            curr_t_ch2 = (curr_t_ch1 + ch2_time_shift) % loop_duration
            virtual_last_t_ch2 = (curr_t_ch2 - dt) % loop_duration
            
            ch2_triggers = get_events_in_window(virtual_last_t_ch2, curr_t_ch2, loop_events, loop_duration)
            if ch2_triggers:
                p, v = ch2_triggers[-1]
                cv3_pitch_out.duty_cycle = int((p / 127) * 65535)
                cv4_vel_out.duty_cycle = int((v / 127) * 65535)
                gate2_out.value = True
                gate2_opened_at = last_update_time
                
        # Handle Loop-Mode Gate Closing 
        if gate1_out.value and (now - gate1_opened_at) >= GATE_LENGTH:
            gate1_out.value = False
        if gate2_out.value and (now - gate2_opened_at) >= GATE_LENGTH:
            gate2_out.value = False

    else:
        # ==========================================
        # LIVE MODE: Pass through and record
        # ==========================================
        if was_in_loop_mode:
            gate1_out.value = False 
            gate2_out.value = False 
            was_in_loop_mode = False
            
        msg = midi.receive()
        
        if isinstance(msg, NoteOn) and msg.velocity > 0:
            if last_live_note_time == 0:
                delta = 0.25 
            else:
                delta = now - last_live_note_time
                
            if delta > 2.0: delta = 2.0
            last_live_note_time = now
            
            pitch_pwm = int((msg.note / 127) * 65535)
            vel_pwm = int((msg.velocity / 127) * 65535)
            
            cv1_pitch_out.duty_cycle = pitch_pwm
            cv2_vel_out.duty_cycle = vel_pwm
            gate1_out.value = True
            
            cv3_pitch_out.duty_cycle = pitch_pwm
            cv4_vel_out.duty_cycle = vel_pwm
            gate2_out.value = True
            
            note_buffer.append((delta, msg.note, msg.velocity))
            if len(note_buffer) > MAX_BUFFER:
                note_buffer.pop(0) 
                
        elif isinstance(msg, NoteOff) or (isinstance(msg, NoteOn) and msg.velocity == 0):
            gate1_out.value = False
            gate2_out.value = False