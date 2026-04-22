import time
import usb_midi
import adafruit_midi
import digitalio
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff

# Import the library, plus the mapping tools and calibration points
from mtm_computer import Computer, map_range, DACzeroPoint, DAChighPoint 

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

# --- HELPER FUNCTION: 1V/OCTAVE PITCH SCALING ---
def midi_to_dac(note):
    # Map MIDI 36 (C2) to 0 Volts (DACzeroPoint)
    # Map MIDI 96 (C7) to +5 Volts (DAChighPoint) 
    # This automatically handles the hardware inversion and 1V/Oct scaling!
    raw_val = map_range(note, 36, 96, DACzeroPoint, DAChighPoint)
    
    # Software Safety Clamp: Ensure we never drop below 0 or exceed 4095
    return max(0, min(4095, int(raw_val)))

# --- 1. HARDWARE SETUP VIA COMPUTER CLASS ---
comp = Computer()

comp.pulse_1_out.direction = digitalio.Direction.OUTPUT
comp.pulse_1_out.value = False
comp.pulse_2_out.direction = digitalio.Direction.OUTPUT
comp.pulse_2_out.value = False

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

# === DISTINCT TIME TRACKERS ===
now = time.monotonic()
last_hw_update_time = now   # 1. Hardware polling clock
last_seq_step_time = now    # 2. Sequencer playhead clock
last_live_note_time = 0     # 3. Live recording clock

HW_UPDATE_INTERVAL = 0.002  # 2ms hardware polling rate

GATE_LENGTH = 0.05    
gate1_opened_at = 0
gate2_opened_at = 0

print("Computer Class Time-Shift Looper ready (Calibrated Pro Routing)!")

while True:
    now = time.monotonic()

    # ==========================================
    # CLOCK 1: HARDWARE POLLING
    # ==========================================
    if now - last_hw_update_time >= HW_UPDATE_INTERVAL:
        comp.update()
        last_hw_update_time = now
    
    n_notes = int((comp.knob_x / 65535) * 29) + 1 
    loop_mode_active = comp.switch < 30000 

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
            
            # Reset the sequencer clock when entering loop mode
            last_seq_step_time = now  
            
            virtual_last_t_ch1 = (curr_t_ch1 - 0.001) % loop_duration
            dt = 0.001 
            
        else:
            # ==========================================
            # CLOCK 2: SEQUENCER PLAYHEAD ADVANCEMENT
            # ==========================================
            dt = now - last_seq_step_time
            last_seq_step_time = now
            
            virtual_last_t_ch1 = curr_t_ch1
            curr_t_ch1 = (curr_t_ch1 + dt) % loop_duration
            
        if len(loop_events) > 0:
            
            # --- PROCESS CHANNEL 1 (Master) ---
            ch1_triggers = get_events_in_window(virtual_last_t_ch1, curr_t_ch1, loop_events, loop_duration)
            if ch1_triggers:
                p, v = ch1_triggers[-1]
                comp.dac_write(0, midi_to_dac(p))
                comp.cv_1_out = int((v / 127) * 65535)
                comp.pulse_1_out.value = True
                gate1_opened_at = now # Set to exact current time, not a past loop time
                
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
                comp.dac_write(1, midi_to_dac(p))
                comp.cv_2_out = int((v / 127) * 65535)
                comp.pulse_2_out.value = True
                gate2_opened_at = now # Set to exact current time
                
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
            
            # ==========================================
            # CLOCK 3: LIVE RECORDING DELTAS
            # ==========================================
            if last_live_note_time == 0:
                delta = 0.25 
            else:
                delta = now - last_live_note_time
                
            if delta > 2.0: delta = 2.0
            last_live_note_time = now
            
            # Master Live Play
            comp.dac_write(0, midi_to_dac(msg.note))
            comp.cv_1_out = int((msg.velocity / 127) * 65535)
            comp.pulse_1_out.value = True
            
            # Follower Live Play
            comp.dac_write(1, midi_to_dac(msg.note))
            comp.cv_2_out = int((msg.velocity / 127) * 65535)
            comp.pulse_2_out.value = True
            
            note_buffer.append((delta, msg.note, msg.velocity))
            if len(note_buffer) > MAX_BUFFER:
                note_buffer.pop(0) 
                
        elif isinstance(msg, NoteOff) or (isinstance(msg, NoteOn) and msg.velocity == 0):
            comp.pulse_1_out.value = False
            comp.pulse_2_out.value = False