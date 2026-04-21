import board
import analogio
import digitalio
import pwmio
import time
import usb_midi
import adafruit_midi
from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff

# --- 1. HARDWARE SETUP ---

# Channel 1 Outputs
cv1_pitch_out = pwmio.PWMOut(board.CV1, frequency=100000, duty_cycle=0)
cv2_vel_out = pwmio.PWMOut(board.CV2, frequency=100000, duty_cycle=0)
gate1_out = digitalio.DigitalInOut(board.GATE1)
gate1_out.direction = digitalio.Direction.OUTPUT

# Channel 2 Outputs (Mirrored)
cv3_pitch_out = pwmio.PWMOut(board.CV3, frequency=100000, duty_cycle=0)
cv4_vel_out = pwmio.PWMOut(board.CV4, frequency=100000, duty_cycle=0)
gate2_out = digitalio.DigitalInOut(board.GATE2)
gate2_out.direction = digitalio.Direction.OUTPUT

# Inputs
pot_x = analogio.AnalogIn(board.POT_1) 
switch_down = digitalio.DigitalInOut(board.SW_DOWN)
switch_down.direction = digitalio.Direction.INPUT
switch_down.pull = digitalio.Pull.UP 

# MIDI Setup
midi = adafruit_midi.MIDI(midi_in=usb_midi.ports[0])

# --- 2. LOOPER VARIABLES ---
MAX_BUFFER = 30
note_buffer = []  # Holds tuples: (time_since_last_note, note_value, velocity)

was_in_loop_mode = False
loop_step = 0
last_step_time = 0
last_live_note_time = 0

GATE_LENGTH = 0.05    
gate_opened_at = 0

print("Mirrored Dual-Channel Looper ready!")

while True:
    n_notes = int((pot_x.value / 65535) * 29) + 1 
    loop_mode_active = not switch_down.value

    if loop_mode_active:
        # ==========================================
        # LOOP MODE: Play back on both channels
        # ==========================================
        
        if not was_in_loop_mode:
            was_in_loop_mode = True
            loop_step = 0
            last_step_time = 0 
        
        if len(note_buffer) > 0:
            current_sequence = note_buffer[-n_notes:]
            now = time.monotonic()
            
            if loop_step >= len(current_sequence):
                loop_step = 0
                
            target_delta, note_to_play, note_velocity = current_sequence[loop_step]
            
            if now - last_step_time >= target_delta:
                
                # Calculate the 16-bit values once
                pitch_pwm = int((note_to_play / 127) * 65535)
                vel_pwm = int((note_velocity / 127) * 65535)
                
                # Output to Channel 1
                cv1_pitch_out.duty_cycle = pitch_pwm
                cv2_vel_out.duty_cycle = vel_pwm
                gate1_out.value = True
                
                # Output to Channel 2
                cv3_pitch_out.duty_cycle = pitch_pwm
                cv4_vel_out.duty_cycle = vel_pwm
                gate2_out.value = True
                
                gate_opened_at = now  
                last_step_time = now
                loop_step += 1
                
        # Close both gates cleanly
        if gate1_out.value and (time.monotonic() - gate_opened_at) >= GATE_LENGTH:
            gate1_out.value = False
            gate2_out.value = False

    else:
        # ==========================================
        # LIVE MODE: Pass through to both channels
        # ==========================================
        if was_in_loop_mode:
            gate1_out.value = False 
            gate2_out.value = False 
            was_in_loop_mode = False
            
        msg = midi.receive()
        
        if isinstance(msg, NoteOn) and msg.velocity > 0:
            now = time.monotonic()
            
            if last_live_note_time == 0:
                delta = 0.25 
            else:
                delta = now - last_live_note_time
                
            if delta > 2.0:
                delta = 2.0
                
            last_live_note_time = now
            
            # Calculate the 16-bit values once
            pitch_pwm = int((msg.note / 127) * 65535)
            vel_pwm = int((msg.velocity / 127) * 65535)
            
            # Output Live to Channel 1
            cv1_pitch_out.duty_cycle = pitch_pwm
            cv2_vel_out.duty_cycle = vel_pwm
            gate1_out.value = True
            
            # Output Live to Channel 2
            cv3_pitch_out.duty_cycle = pitch_pwm
            cv4_vel_out.duty_cycle = vel_pwm
            gate2_out.value = True
            
            # Save to memory
            note_buffer.append((delta, msg.note, msg.velocity))
            
            if len(note_buffer) > MAX_BUFFER:
                note_buffer.pop(0) 
                
        elif isinstance(msg, NoteOff) or (isinstance(msg, NoteOn) and msg.velocity == 0):
            # Close both gates
            gate1_out.value = False
            gate2_out.value = False