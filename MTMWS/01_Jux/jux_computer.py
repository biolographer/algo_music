# --- NOTES ---
#
# THIS IS A REFACTORED VERSION OF midi_loop_timeshift+Computer.py
# it implements the looper as a class
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

def midi_to_dac(note):
    raw_val = map_range(note, 36, 96, DACzeroPoint, DAChighPoint)
    return max(0, min(4095, int(raw_val)))

def trigger_voice(comp, state, channel, note, velocity, now):
    """Handles the repetitive DAC and CV routing for a single voice"""
    comp.dac_write(channel, midi_to_dac(note))
    if channel == 0:
        comp.cv_1_out = int((velocity / 127) * 65535)
        comp.pulse_1_out.value = True
        state.gate1_opened_at = now
    elif channel == 1:
        comp.cv_2_out = int((velocity / 127) * 65535)
        comp.pulse_2_out.value = True
        state.gate2_opened_at = now

def check_gate_timeouts(comp, state, now):
    """Closes gates if they have been open longer than GATE_LENGTH"""
    if comp.pulse_1_out.value and (now - state.gate1_opened_at) >= state.GATE_LENGTH:
        comp.pulse_1_out.value = False
    if comp.pulse_2_out.value and (now - state.gate2_opened_at) >= state.GATE_LENGTH:
        comp.pulse_2_out.value = False

# --- STATE MANAGEMENT ---
class LooperState:
    """A simple container to hold all our changing variables in one place"""
    def __init__(self):
        self.MAX_BUFFER = 30
        self.note_buffer = []  
        self.was_in_loop_mode = False
        #self.last_n_notes = 0
        self.last_n_notes_ch1 = 0
        self.last_n_notes_ch2 = 0

        # Timeline variables
        #self.loop_events = []
        self.loop_events_ch1 = []
        self.loop_events_ch2 = []
        #self.loop_duration = 0.1
        self.loop_duration_ch1 = 0.1
        self.loop_duration_ch2 = 0.1
        self.curr_t_ch1 = 0.0
        self.curr_t_ch2 = 0.0
        self.max_advance = 0.0

        # Clocks
        now = time.monotonic()
        self.last_hw_update_time = now
        self.last_seq_step_time = now
        self.last_live_note_time = 0

        # Gates
        self.GATE_LENGTH = 0.05    
        self.gate1_opened_at = 0
        self.gate2_opened_at = 0

# --- CORE OPERATION FUNCTIONS ---

def process_loop_mode(comp, state, n_notes_ch1, n_notes_ch2, now):
    """Handles independent sequencer advancement for two playheads"""
    # --- UPDATE CHANNEL 1 SEQUENCE ---
    if not state.was_in_loop_mode or n_notes_ch1 != state.last_n_notes_ch1:
        state.last_n_notes_ch1 = n_notes_ch1
        state.loop_events_ch1 = []
        current_t = 0.0
        # Grab notes from buffer
        seq1 = state.note_buffer[-n_notes_ch1:] if state.note_buffer else []
        for d, p, v in seq1:
            current_t += d
            state.loop_events_ch1.append((current_t, p, v))
        state.loop_duration_ch1 = current_t if current_t > 0 else 0.1
        state.curr_t_ch1 = 0.0

    # --- UPDATE CHANNEL 2 SEQUENCE ---
    if not state.was_in_loop_mode or n_notes_ch2 != state.last_n_notes_ch2:
        state.last_n_notes_ch2 = n_notes_ch2
        state.loop_events_ch2 = []
        current_t = 0.0
        # Grab notes from buffer
        seq2 = state.note_buffer[-n_notes_ch2:] if state.note_buffer else []
        for d, p, v in seq2:
            current_t += d
            state.loop_events_ch2.append((current_t, p, v))
        state.loop_duration_ch2 = current_t if current_t > 0 else 0.1
        state.curr_t_ch2 = 0.0

    state.was_in_loop_mode = True

    # --- TIME ADVANCEMENT ---
    dt = now - state.last_sesq_step_time
    state.last_seq_step_time = now

    # --- PROCESS CHANNEL 1 ---
    if state.loop_events_ch1:
        v_last_t1 = state.curr_t_ch1
        state.curr_t_ch1 = (state.curr_t_ch1 + dt) % state.loop_duration_ch1
        triggers1 = get_events_in_window(v_last_t1, state.curr_t_ch1, state.loop_events_ch1, state.loop_duration_ch1)
        if triggers1:
            p, v = triggers1[-1]
            trigger_voice(comp, state, 0, p, v, now)

    # --- PROCESS CHANNEL 2 ---
    if state.loop_events_ch2:
        v_last_t2 = state.curr_t_ch2
        state.curr_t_ch2 = (state.curr_t_ch2 + dt) % state.loop_duration_ch2
        triggers2 = get_events_in_window(v_last_t2, state.curr_t_ch2, state.loop_events_ch2, state.loop_duration_ch2)
        if triggers2:
            p, v = triggers2[-1]
            trigger_voice(comp, state, 1, p, v, now)

def process_live_mode(comp, state, midi, now):
    """Handles MIDI pass-through, recording, and exiting loop mode"""
    # 1. State Transition: Exiting Loop Mode
    if state.was_in_loop_mode:
        comp.pulse_1_out.value = False 
        comp.pulse_2_out.value = False 
        state.was_in_loop_mode = False
        
    # 2. Process incoming MIDI
    msg = midi.receive()
    if isinstance(msg, NoteOn) and msg.velocity > 0:
        
        # Calculate timing delta for buffer
        if state.last_live_note_time == 0:
            delta = 0.25 
        else:
            delta = min(now - state.last_live_note_time, 2.0)
            
        state.last_live_note_time = now
        
        # Play both voices
        trigger_voice(comp, state, 0, msg.note, msg.velocity, now)
        trigger_voice(comp, state, 1, msg.note, msg.velocity, now)
        
        # Record to buffer
        state.note_buffer.append((delta, msg.note, msg.velocity))
        if len(state.note_buffer) > state.MAX_BUFFER:
            state.note_buffer.pop(0) 
            
    elif isinstance(msg, NoteOff) or (isinstance(msg, NoteOn) and msg.velocity == 0):
        comp.pulse_1_out.value = False
        comp.pulse_2_out.value = False

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

# Instantiate our state container
state = LooperState()

print("Computer Class Time-Shift Looper ready (Refactored)!")

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

    loop_mode_active = comp.switch < 30000 

    # 3. Process Logic
    if loop_mode_active:
        process_loop_mode(comp, state, n_notes_ch1, n_notes_ch2, now)
    else:
        process_live_mode(comp, state, midi, now)
        
    # 4. Maintenance / Cleanup
    check_gate_timeouts(comp, state, now)