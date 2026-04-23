# --- NOTES ---
#
# THIS IS A REFACTORED VERSION OF midi_loop_timeshift+Computer.py
# it implements the looper as a class with NoteOff duration tracking
# and a chord filter for monophonic priority.
# Implements midi clock
#
# --- ----- ---

import time
import usb_midi
import adafruit_midi
import digitalio
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff
from adafruit_midi.timing_clock import TimingClock
from adafruit_midi.start import Start
from adafruit_midi.stop import Stop
from mtm_computer import Computer, map_range, DACzeroPoint, DAChighPoint 

# --- HELPER FUNCTIONS ---
def get_events_in_window(start_t, end_t, events, duration):
    """Returns events that fall within the start and end tick, wrapping around the loop"""
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

def check_gate_timeouts(comp, state):
    """Closes gates if the global tick has exceeded their tracked duration"""
    if comp.pulse_1_out.value and state.global_tick_count >= state.gate1_close_tick:
        comp.pulse_1_out.value = False
    if comp.pulse_2_out.value and state.global_tick_count >= state.gate2_close_tick:
        comp.pulse_2_out.value = False

# --- STATE MANAGEMENT ---
class LooperState:
    """A simple container to hold all our changing variables in one place"""
    def __init__(self):
        self.MAX_BUFFER = 30
        # Buffer stores: [delta_ticks, note, velocity, duration_ticks]
        self.note_buffer = []  
        
        self.was_in_loop_mode = False
        self.last_n_notes_ch1 = 0
        self.last_n_notes_ch2 = 0

        # Timeline variables
        self.loop_events_ch1 = []
        self.loop_events_ch2 = []
        self.loop_duration_ch1 = 24
        self.loop_duration_ch2 = 24
        self.curr_t_ch1 = 0
        self.curr_t_ch2 = 0

        # Clock sync
        self.global_tick_count = 0
        self.use_external_clock = False
        self.last_internal_tick_time = time.monotonic()
        self.last_hw_update_time = time.monotonic()
        
        # Step tracking
        self.last_seq_step_tick = 0
        self.last_live_note_tick = -1

        # Duration & Live Note Tracking
        self.active_live_note = None
        self.active_note_start_tick = 0
        self.gate1_close_tick = 0
        self.gate2_close_tick = 0

        # Switch down tracking
        self.sw_down_started_at = 0
        self.reverse_ch2 = False
        self.last_reverse = False
        self.long_press_triggered = False

# --- CORE OPERATION FUNCTIONS ---

def process_loop_mode(comp, state, n_notes_ch1, n_notes_ch2, reverse_ch2):
    """Handles independent sequencer advancement based on global clock ticks"""
    
    buf_len = len(state.note_buffer)

    # --- UPDATE SEQUENCES (Triggered on switch flip or knob turn) ---
    if not state.was_in_loop_mode or n_notes_ch1 != state.last_n_notes_ch1:
        state.last_n_notes_ch1 = n_notes_ch1
        state.loop_events_ch1 = []
        seq1 = state.note_buffer[-(n_notes_ch1 + 1):-1]

        current_t = 0
        for d, p, v, dur in seq1:
            current_t += d
            state.loop_events_ch1.append((current_t, p, v, dur))
        state.loop_duration_ch1 = current_t if current_t > 0 else 24
        state.curr_t_ch1 = 0

    if not state.was_in_loop_mode or n_notes_ch2 != state.last_n_notes_ch2 or reverse_ch2 != state.last_reverse:
        state.last_n_notes_ch2 = n_notes_ch2
        state.last_reverse = reverse_ch2
        state.loop_events_ch2 = []
        
        seq2 = state.note_buffer[-(n_notes_ch2 + 1):-1] if buf_len > n_notes_ch2 else state.note_buffer[:-1]
        if reverse_ch2:
            seq2 = list(reversed(seq2))
            
        current_t = 0
        for d, p, v, dur in seq2:
            current_t += d
            state.loop_events_ch2.append((current_t, p, v, dur))
        state.loop_duration_ch2 = current_t if current_t > 0 else 24
        state.curr_t_ch2 = 0

    # Reset step tracker if we just flipped the switch to prevent massive time jumps
    if not state.was_in_loop_mode:
        state.last_seq_step_tick = state.global_tick_count
        
    state.was_in_loop_mode = True

    # --- TIME ADVANCEMENT ---
    dt_ticks = state.global_tick_count - state.last_seq_step_tick
    state.last_seq_step_tick = state.global_tick_count

    if dt_ticks > 0:
        # --- PROCESS CHANNEL 1 ---
        if state.loop_events_ch1:
            v_last_t1 = state.curr_t_ch1
            state.curr_t_ch1 = (state.curr_t_ch1 + dt_ticks) % state.loop_duration_ch1
            triggers1 = get_events_in_window(v_last_t1, state.curr_t_ch1, state.loop_events_ch1, state.loop_duration_ch1)
            for p, v, dur in triggers1:
                trigger_voice(comp, 0, p, v)
                state.gate1_close_tick = state.global_tick_count + dur

        # --- PROCESS CHANNEL 2 ---
        if state.loop_events_ch2:
            v_last_t2 = state.curr_t_ch2
            state.curr_t_ch2 = (state.curr_t_ch2 + dt_ticks) % state.loop_duration_ch2
            triggers2 = get_events_in_window(v_last_t2, state.curr_t_ch2, state.loop_events_ch2, state.loop_duration_ch2)
            for p, v, dur in triggers2:
                trigger_voice(comp, 1, p, v)
                state.gate2_close_tick = state.global_tick_count + dur

def handle_live_notes(comp, state, msg):
    """Handles MIDI pass-through, recording, chords, and legatos"""
    if state.was_in_loop_mode:
        comp.pulse_1_out.value = False 
        comp.pulse_2_out.value = False 
        state.was_in_loop_mode = False
        
    if isinstance(msg, NoteOn) and msg.velocity > 0:
        
        # Calculate timing delta in ticks
        if state.last_live_note_tick == -1:
            delta_ticks = 24 # Default to 1 quarter note for the very first note
        else:
            delta_ticks = state.global_tick_count - state.last_live_note_tick
            
        state.last_live_note_tick = state.global_tick_count

        # Legato interrupt: Finalize previous note's duration if still active
        if state.active_live_note is not None and len(state.note_buffer) > 0:
            state.note_buffer[-1][3] = max(1, state.global_tick_count - state.active_note_start_tick)

        # Chord Filter: If played within 1 tick (~20ms at 120bpm), treat as chord
        if delta_ticks <= 1 and len(state.note_buffer) > 0:
            prev_delta = state.note_buffer[-1][0]
            # Overwrite previous note, maintain original timing
            state.note_buffer[-1] = [prev_delta, msg.note, msg.velocity, 2] 
        else:
            state.note_buffer.append([delta_ticks, msg.note, msg.velocity, 2])
            if len(state.note_buffer) > state.MAX_BUFFER:
                state.note_buffer.pop(0) 

        state.active_live_note = msg.note
        state.active_note_start_tick = state.global_tick_count
        
        trigger_voice(comp, 0, msg.note, msg.velocity)
        trigger_voice(comp, 1, msg.note, msg.velocity)
        
        # Keep gates open until NoteOff arrives
        state.gate1_close_tick = state.global_tick_count + 9999
        state.gate2_close_tick = state.global_tick_count + 9999
            
    elif isinstance(msg, NoteOff) or (isinstance(msg, NoteOn) and msg.velocity == 0):
        if msg.note == state.active_live_note:
            duration_ticks = max(1, state.global_tick_count - state.active_note_start_tick)
            
            if len(state.note_buffer) > 0:
                state.note_buffer[-1][3] = duration_ticks
                
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
INTERNAL_TICK_RATE = 0.02083 # 120 BPM fallback (60 / (120 * 24))

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
    buffer_ready = len(state.note_buffer) > (max(n_notes_ch1, n_notes_ch2) + 3)
    
    sw_val = comp.switch
    is_mid = (20000 < sw_val < 45000)
    is_down = (sw_val < 20000)
    loop_mode_active = (is_mid or is_down) and buffer_ready

    # Handle Reverse Latch
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

    # 3. Global MIDI & Clock Processing
    msg = midi.receive()
    while msg is not None:
        if isinstance(msg, TimingClock):
            state.use_external_clock = True
            state.global_tick_count += 1
        elif isinstance(msg, Start):
            state.global_tick_count = 0
            comp.pulse_1_out.value = False
            comp.pulse_2_out.value = False
        elif isinstance(msg, Stop):
            comp.pulse_1_out.value = False
            comp.pulse_2_out.value = False
        elif not loop_mode_active:
            handle_live_notes(comp, state, msg)
        
        msg = midi.receive() # Read next message to clear buffer

    # 4. Internal Fallback Clock 
    if not state.use_external_clock:
        if now - state.last_internal_tick_time >= INTERNAL_TICK_RATE:
            state.global_tick_count += 1
            state.last_internal_tick_time = now

    # 5. Process Loop Logic
    if loop_mode_active:
        process_loop_mode(comp, state, n_notes_ch1, n_notes_ch2, state.reverse_ch2)
        
    # 6. Gate Timeouts (based on ticks)
    check_gate_timeouts(comp, state)