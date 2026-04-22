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
        self.last_n_notes = 0

        # Timeline variables
        self.loop_events = []
        self.loop_duration = 0.1
        self.max_advance = 0.0
        self.curr_t_ch1 = 0.0

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

def process_loop_mode(comp, state, n_notes, now):
    """Handles all sequencer advancement and playback logic"""
    # 1. State Transition: Entering Loop Mode
    if not state.was_in_loop_mode or n_notes != state.last_n_notes:
        state.was_in_loop_mode = True
        state.last_n_notes = n_notes
        
        current_sequence = state.note_buffer[-n_notes:] if state.note_buffer else []
        state.loop_events = []
        current_t = 0.0
        
        for d, p, v in current_sequence:
            current_t += d
            state.loop_events.append((current_t, p, v))
            
        state.loop_duration = current_t if current_t > 0 else 0.1
        state.max_advance = current_sequence[1][0] if len(current_sequence) > 1 else 0.0
        state.curr_t_ch1 = state.loop_events[0][0] if state.loop_events else 0.0
        
        state.last_seq_step_time = now  
        virtual_last_t_ch1 = (state.curr_t_ch1 - 0.001) % state.loop_duration
        dt = 0.001 
        
    # 2. Normal Loop Advancement
    else:
        dt = now - state.last_seq_step_time
        state.last_seq_step_time = now
        virtual_last_t_ch1 = state.curr_t_ch1
        state.curr_t_ch1 = (state.curr_t_ch1 + dt) % state.loop_duration
        
    # 3. Trigger Processing
    if len(state.loop_events) > 0:
        # Process Master Channel 1
        ch1_triggers = get_events_in_window(virtual_last_t_ch1, state.curr_t_ch1, state.loop_events, state.loop_duration)
        if ch1_triggers:
            p, v = ch1_triggers[-1]
            trigger_voice(comp, state, 0, p, v, now)
            
        # Calculate Time Shift for Follower
        pot2_val = comp.knob_main 
        if pot2_val < 25000:
            ch2_time_shift = ((25000 - pot2_val) / 25000.0) * state.max_advance
        elif pot2_val > 40000:
            ch2_time_shift = - (((pot2_val - 40000) / 25535.0) * 1.0) 
        else:
            ch2_time_shift = 0.0
            
        # Process Follower Channel 2
        curr_t_ch2 = (state.curr_t_ch1 + ch2_time_shift) % state.loop_duration
        virtual_last_t_ch2 = (curr_t_ch2 - dt) % state.loop_duration
        
        ch2_triggers = get_events_in_window(virtual_last_t_ch2, curr_t_ch2, state.loop_events, state.loop_duration)
        if ch2_triggers:
            p, v = ch2_triggers[-1]
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
    n_notes = int((comp.knob_x / 65536) * 11) + 2
    
    loop_mode_active = comp.switch < 30000 

    # 3. Process Logic
    if loop_mode_active:
        process_loop_mode(comp, state, n_notes, now)
    else:
        process_live_mode(comp, state, midi, now)
        
    # 4. Maintenance / Cleanup
    check_gate_timeouts(comp, state, now)