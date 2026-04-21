import time
import usb_midi
import adafruit_midi
import digitalio
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff
from mtm_computer import Computer  # Import your provided library

# --- HELPER FUNCTION: TIMELINE SCANNER ---
def get_events_in_window(start_t, end_t, events, duration):
    triggers = []
    if start_t < end_t:
        for t, p, v in events:
            if start_t < t <= end_t:
                triggers.append((p, v))
    else:
        for t, p, v in events:
            if start_t < t <= duration:
                triggers.append((p, v))
            if 0 <= t <= end_t:
                triggers.append((p, v))
    return triggers

# --- 1. HARDWARE SETUP VIA COMPUTER CLASS ---
comp = Computer()

# The Computer class creates pulse_1_out/pulse_2_out but doesn't set them as outputs.
# We must explicitly set their direction here so we can use them as Gates.
comp.pulse_1_out.direction = digitalio.Direction.OUTPUT
comp.pulse_2_out.direction = digitalio.Direction.OUTPUT

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

print("Computer Class Time-Shift Looper ready (Pro Routing)!")

while True:
    # IMPORTANT: Update the computer class every cycle to read the multiplexers!
    comp.update() 
    
    # Scale knob_x (0-65535) to 1-30 notes
    n_notes = int((comp.knob_x / 65535) * 29) + 1 
    
    # The switch on the Computer reads as an analog value. 
    # Down is roughly 0, Up is roughly 65535.
    loop_mode_active = comp.switch < 30000 
    
    now = time.monotonic()

    if loop_mode_active:
        # ==========================================
        # LOOP MODE: Dual Playheads with Time Shift
        # ==========================================
        if not was_in_loop_mode or n_notes != last_n_notes:
            was_in_loop_mode = True
            last_n_notes = n_notes
            
            current_sequence = note_buffer[-n_notes:] if note_buffer else []
            loop_events = []
            current_t = 0.0
            
            for d, p, v in current_sequence:
                current_t += d
                loop_events.append((current_t, p, v))
                
            loop_duration = current_t if current_t > 0 else 0.1
            
            if len(current_sequence) > 1:
                max_advance = current_sequence[1][0] 
            else:
                max_advance = 0.0
                
            curr_t_ch1 = loop_events[0][0] if loop_events else 0.0
            last_update_time = now
            
            virtual_last_t_ch1 = (curr_t_ch1 - 0.001) % loop_duration
            dt = 0.001 
            
        else:
            dt = now - last_update_time
            last_update_time = now
            virtual_last_t_ch1 = curr_t_ch1
            curr_t_ch1 = (curr_t_ch1 + dt) % loop_duration
            
        if len(loop_events) > 0:
            
            # --- PROCESS CHANNEL 1 (Master) ---
            ch1_triggers = get_events_in_window(virtual_last_t_ch1, curr_t_ch1, loop_events, loop_duration)
            if ch1_triggers:
                p, v = ch1_triggers[-1]
                # CH1 Pitch to DAC Channel A (0)
                comp.dac_write(0, int((p / 127) * 4095))
                # CH1 Velocity to PWM CV 1
                comp.cv_1_out = int((v / 127) * 65535)
                
                comp.pulse_1_out.value = True
                gate1_opened_at = last_update_time
                
            # --- CALCULATE BIG KNOB OFFSET ---
            pot2_val = comp.knob_main 
            
            if pot2_val < 25000:
                advance_factor = (25000 - pot2_val) / 25000.0
                ch2_time_shift = advance_factor * max_advance
            elif pot2_val > 40000:
                delay_factor = (pot2_val - 40000) / 25535.0
                ch2_time_shift = - (delay_factor * 1.0) 
            else:
                ch2_time_shift = 0.0
                
            # --- PROCESS CHANNEL 2 (Follower) ---
            curr_t_ch2 = (curr_t_ch1 + ch2_time_shift) % loop_duration
            virtual_last_t_ch2 = (curr_t_ch2 - dt) % loop_duration
            
            ch2_triggers = get_events_in_window(virtual_last_t_ch2, curr_t_ch2, loop_events, loop_duration)
            if ch2_triggers:
                p, v = ch2_triggers[-1]
                # CH2 Pitch to DAC Channel B (1)
                comp.dac_write(1, int((p / 127) * 4095))
                # CH2 Velocity to PWM CV 2
                comp.cv_2_out = int((v / 127) * 65535)
                
                comp.pulse_2_out.value = True
                gate2_opened_at = last_update_time
                
        # Handle Loop-Mode Gate Closing 
        if comp.pulse_1_out.value and (now - gate1_opened_at) >= GATE_LENGTH:
            comp.pulse_1_out.value = False
        if comp.pulse_2_out.value and (now - gate2_opened_at) >= GATE_LENGTH:
            comp.pulse_2_out.value = False

    else:
        # ==========================================
        # LIVE MODE: Pass through and record
        # ==========================================
        if was_in_loop_mode:
            comp.pulse_1_out.value = False 
            comp.pulse_2_out.value = False 
            was_in_loop_mode = False
            
        msg = midi.receive()
        
        if isinstance(msg, NoteOn) and msg.velocity > 0:
            if last_live_note_time == 0:
                delta = 0.25 
            else:
                delta = now - last_live_note_time
                
            if delta > 2.0: delta = 2.0
            last_live_note_time = now
            
            # Master Out: Pitch (DAC A) & Velocity (CV 1)
            comp.dac_write(0, int((msg.note / 127) * 4095))
            comp.cv_1_out = int((msg.velocity / 127) * 65535)
            comp.pulse_1_out.value = True
            
            # Follower Out: Pitch (DAC B) & Velocity (CV 2)
            comp.dac_write(1, int((msg.note / 127) * 4095))
            comp.cv_2_out = int((msg.velocity / 127) * 65535)
            comp.pulse_2_out.value = True
            
            note_buffer.append((delta, msg.note, msg.velocity))
            if len(note_buffer) > MAX_BUFFER:
                note_buffer.pop(0) 
                
        elif isinstance(msg, NoteOff) or (isinstance(msg, NoteOn) and msg.velocity == 0):
            comp.pulse_1_out.value = False
            comp.pulse_2_out.value = False