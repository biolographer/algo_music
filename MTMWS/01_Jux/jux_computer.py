# --- NOTES ---
#
# THIS IS A REFACTORED VERSION OF midi_loop_timeshift+Computer.py
# it implements the looper as a class with NoteOff duration tracking
# and a chord filter for monophonic priority.
#
# --- ----- ---

import time
import usb_midi
import adafruit_midi
import digitalio
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff
from mtm_computer import Computer, map_range, DACzeroPoint, DAChighPoint 

# --- HELPER FUNCTIONS ---
def get_events_in_window(start_t, end_t, events, duration):
    triggers = []
    if start_t < end_t:
        for t, p, v, dur in events:
            if start_t < t <= end_t:
                triggers.append((p, v, dur))
    else:
        for t, p, v, dur in events:
            if start_t < t <= duration:
                triggers.append((p, v, dur))
            if 0 <= t <= end_t:
                triggers.append((p, v, dur))
    return triggers

def midi_to_dac(note):
    raw_val = map_range(note, 36, 96, DACzeroPoint, DAChighPoint)
    return max(0, min(4095, int(raw_val)))

def trigger_voice(comp, channel, note, velocity):
    """Handles the repetitive DAC and CV routing for a single voice"""
    comp.dac_write(channel, midi_to_dac(note))
    if channel == 0:
        comp.cv_1_out = int((velocity / 127) * 65535)
        comp.pulse_1_out.value = True
    elif channel == 1:
        comp.cv_2_out = int((velocity / 127) * 65535)
        comp.pulse_2_out.value = True

def check_gate_timeouts(comp, state, now):
    """Closes gates if they have exceeded their tracked duration"""
    if comp.pulse_1_out.value and now >= state.gate1_close_time:
        comp.pulse_1_out.value = False
    if comp.pulse_2_out.value and now >= state.gate2_close_time:
        comp.pulse_2_out.value = False

# --- STATE MANAGEMENT ---
class LooperState:
    """A simple container to hold all our changing variables in one place"""
    def __init__(self):
        self.MAX_BUFFER = 30
        self.note_buffer = []  # Stores: [delta, note, velocity, duration]
        self.was_in_loop_mode = False
        self.last_n_notes_ch1 = 0
        self.last_n_notes_ch2 = 0

        # Timeline variables
        self.loop_events_ch1 = []
        self.loop_events_ch2 = []
        self.loop_duration_ch1 = 0.1
        self.loop_duration_ch2 = 0.1
        self.curr_t_ch1 = 0.0
        self.curr_t_ch2 = 0.0

        # Clocks
        now = time.monotonic()
        self.last_hw_update_time = now
        self.last_seq_step_time = now
        self.last_live_note_time = 0

        # Duration & Live Note Tracking
        self.active_live_note = None
        self.active_note_start_time = 0
        self.gate1_close_time = 0
        self.gate2_close_time = 0

        # Switch down tracking
        self.sw_down_started_at = 0
        self.reverse_ch2 = False
        self.last_reverse = False
        self.long_press_triggered = False

# --- CORE OPERATION FUNCTIONS ---

def process_loop_mode(comp, state, n_notes_ch1, n_notes_ch2, reverse_ch2, now):
    """Handles independent sequencer advancement with 'Completed Note' logic"""
    
    buf_len = len(state.note_buffer)

    # --- UPDATE CHANNEL 1 SEQUENCE ---
    if not state.was_in_loop_mode or n_notes_ch1 != state.last_n_notes_ch1:
        state.last_n_notes_ch1 = n_notes_ch1
        state.loop_events_ch1 = []

        seq1 = state.note_buffer[-(n_notes_ch1 + 1):-1]

        current_t = 0.0
        for d, p, v, dur in seq1:
            current_t += d
            state.loop_events_ch1.append((current_t, p, v, dur))
        state.loop_duration_ch1 = current_t if current_t > 0 else 0.1
        state.curr_t_ch1 = 0.0

    # --- UPDATE CHANNEL 2 SEQUENCE (Reverse mode enabled) ---
    if not state.was_in_loop_mode or n_notes_ch2 != state.last_n_notes_ch2 or reverse_ch2 != state.last_reverse:
        state.last_n_notes_ch2 = n_notes_ch2
        state.last_reverse = reverse_ch2
        state.loop_events_ch2 = []
        
        seq2 = state.note_buffer[-(n_notes_ch2 + 1):-1] if buf_len > n_notes_ch2 else state.note_buffer[:-1]
        
        if reverse_ch2:
            seq2 = list(reversed(seq2))
            
        current_t = 0.0
        for d, p, v, dur in seq2:
            current_t += d
            state.loop_events_ch2.append((current_t, p, v, dur))
        state.loop_duration_ch2 = current_t if current_t > 0 else 0.1
        state.curr_t_ch2 = 0.0

    state.was_in_loop_mode = True

    # --- TIME ADVANCEMENT ---
    dt = now - state.last_seq_step_time
    state.last_seq_step_time = now

    # --- PROCESS CHANNEL 1 ---
    if state.loop_events_ch1:
        v_last_t1 = state.curr_t_ch1
        state.curr_t_ch1 = (state.curr_t_ch1 + dt) % state.loop_duration_ch1
        triggers1 = get_events_in_window(v_last_t1, state.curr_t_ch1, state.loop_events_ch1, state.loop_duration_ch1)
        if triggers1:
            p, v, dur = triggers1[-1]
            trigger_voice(comp, 0, p, v)
            state.gate1_close_time = now + dur

    # --- PROCESS CHANNEL 2 ---
    if state.loop_events_ch2:
        v_last_t2 = state.curr_t_ch2
        state.curr_t_ch2 = (state.curr_t_ch2 + dt) % state.loop_duration_ch2
        triggers2 = get_events_in_window(v_last_t2, state.curr_t_ch2, state.loop_events_ch2, state.loop_duration_ch2)
        if triggers2:
            p, v, dur = triggers2[-1]
            trigger_voice(comp, 1, p, v)
            state.gate2_close_time = now + dur

def process_live_mode(comp, state, midi, now):
    """Handles MIDI pass-through, recording, chords, and legatos"""
    # 1. State Transition: Exiting Loop Mode
    if state.was_in_loop_mode:
        comp.pulse_1_out.value = False 
        comp.pulse_2_out.value = False 
        state.was_in_loop_mode = False
        
    CHORD_WINDOW = 0.025  # 25ms threshold for simultaneous notes
    msg = midi.receive()
    
    if isinstance(msg, NoteOn) and msg.velocity > 0:
        
        # Calculate timing delta
        if state.last_live_note_time == 0:
            delta = 0.25 
            clean_delta = 0.25
        else:
            delta = now - state.last_live_note_time
            clean_delta = min(delta, 2.0)
            
        state.last_live_note_time = now

        # Legato interrupt: Finalize previous note's duration if still active
        if state.active_live_note is not None and len(state.note_buffer) > 0:
            state.note_buffer[-1][3] = now - state.active_note_start_time

        # Chord Filter
        if delta < CHORD_WINDOW and len(state.note_buffer) > 0:
            # Overwrite the last note instead of appending, preserving previous delta
            prev_delta = state.note_buffer[-1][0]
            state.note_buffer[-1] = [prev_delta, msg.note, msg.velocity, 0.1]
        else:
            # Normal sequential note
            state.note_buffer.append([clean_delta, msg.note, msg.velocity, 0.1])
            if len(state.note_buffer) > state.MAX_BUFFER:
                state.note_buffer.pop(0) 

        state.active_live_note = msg.note
        state.active_note_start_time = now
        
        # Play both voices
        trigger_voice(comp, 0, msg.note, msg.velocity)
        trigger_voice(comp, 1, msg.note, msg.velocity)
        
        # Keep gates open indefinitely in live mode (closed by NoteOff)
        state.gate1_close_time = now + 999
        state.gate2_close_time = now + 999
            
    elif isinstance(msg, NoteOff) or (isinstance(msg, NoteOn) and msg.velocity == 0):
        # Match NoteOff to our current active note
        if msg.note == state.active_live_note:
            duration = now - state.active_note_start_time
            
            # Update the buffer with actual duration
            if len(state.note_buffer) > 0:
                state.note_buffer[-1][3] = duration
                
            comp.pulse_1_out.value = False
            comp.pulse_2_out.value = False
            state.active_live_note = None


# ==========================================
# HARDWARE INITIALIZATION
# ==========================================
comp = Computer()
comp.pulse_1_out.direction = digitalio.Direction.OUTPUT
comp.pulse_2_out.direction = digitalio.Direction.OUTPUT
comp.pulse_1_out.value = False
comp.pulse_2_out.value = False

midi = adafruit_midi.MIDI(midi_in=usb_midi.ports[0])
HW_UPDATE_INTERVAL = 0.002  

LATCH_TIME = 0.5
state = LooperState()

print("Computer Class and Time-Shift Looper ready!")

# ==========================================
# MAIN LOOP
# ==========================================
while True:
    now = time.monotonic()

    # 1. Hardware Polling
    if now - state.last_hw_update_time >= HW_UPDATE_INTERVAL:
        comp.update()
        state.last_hw_update_time = now
    
    # 2. Read UI state
    n_notes_ch1 = int((comp.knob_x / 65536) * 11) + 2 
    n_notes_ch2 = int((comp.knob_y / 65536) * 11) + 2 

    buffer_ready = len(state.note_buffer) > ( max(n_notes_ch1, n_notes_ch2) + 3 )
    sw_val = comp.switch

    is_mid = (20000 < sw_val < 45000)
    is_down = (sw_val < 20000)
    loop_mode_active = (is_mid or is_down) and buffer_ready

    if is_down:
        if state.sw_down_started_at == 0:
            state.sw_down_started_at = now
            state.long_press_triggered = False
        
        if (now - state.sw_down_started_at) >= LATCH_TIME and not state.long_press_triggered:
            state.reverse_ch2 = not state.reverse_ch2  
            state.long_press_triggered = True         
    else:
        state.sw_down_started_at = 0
        state.long_press_triggered = False

    # 3. Process Logic
    if loop_mode_active:
        process_loop_mode(comp, state, n_notes_ch1, n_notes_ch2, state.reverse_ch2, now)
    else:
        process_live_mode(comp, state, midi, now)
        
    # 4. Maintenance / Cleanup
    check_gate_timeouts(comp, state, now)