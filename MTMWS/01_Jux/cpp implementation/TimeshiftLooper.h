#ifndef TIMESHIFTLOOPER_H
#define TIMESHIFTLOOPER_H

#include "ComputerCard.h"
#include "pico/util/queue.h"
#include <stdint.h>

// 1. Struct for Core 0 to Core 1 communication
struct MIDIMessage {
    uint8_t status;
    uint8_t data1;
    uint8_t data2;
};

// 2. Declare the queue as extern AT GLOBAL SCOPE
extern queue_t midi_queue;

// --- FIXED-POINT MATH HELPERS ---
#define Q16_ONE 65536
static inline uint32_t IntToQ16(uint32_t x) { return x << 16; }
static inline uint32_t Q16ToInt(uint32_t x) { return x >> 16; }
static inline uint32_t MulQ16(uint32_t a_Q16, uint32_t b_Q16) {
    return (uint32_t)(((uint64_t)a_Q16 * (uint64_t)b_Q16) >> 16);
}

// --- HELPER STRUCTS ---
struct NoteEvent {
    uint32_t delta_ticks;
    uint8_t note;
    uint8_t velocity;
    uint32_t duration_ticks;
};

struct LoopEvent {
    uint32_t t_Q16;
    uint8_t note;
    uint8_t velocity;
    uint32_t duration_Q16;
};

// --- CORE LOOPER CLASS ---
class TimeshiftLooper : public ComputerCard {
public:
    static constexpr int MAX_BUFFER = 30;
    static constexpr uint32_t LATCH_SAMPLES = 24000; 
    static constexpr uint32_t INTERNAL_TICK_SAMPLES = 1000; 

    // --- ENVELOPE / VCA STATE ---
    enum EnvState { IDLE, ATTACK, RELEASE };

    struct DigitalVCA {
        EnvState state = IDLE;
        uint32_t current_level_Q16 = 0;      
        uint32_t target_level_Q16 = 0;       
        uint32_t attack_step = 2000;  
        uint32_t release_step = 2000; 
        uint32_t vel_timing_offset = 0; 
    };

    DigitalVCA vca1;
    DigitalVCA vca2;

    // State Variables
    NoteEvent note_buffer[MAX_BUFFER];
    int buffer_count = 0;

    // --- SNAPSHOT BUFFER FOR LOOP SYNC ---
    NoteEvent snapshot_buffer[MAX_BUFFER];
    int snapshot_buffer_count = 0;

    // Physical Input Tracking
    bool last_pulse_gate = false;
    uint8_t last_cv_note = 0;

    bool was_in_loop_mode = false;
    int last_n_notes_ch1 = 0;
    int last_n_notes_ch2 = 0;

    // Timeline Variables
    LoopEvent loop_events_ch1[MAX_BUFFER];
    int num_events_ch1 = 0;
    uint32_t loop_duration_ch1_Q16 = IntToQ16(24);
    uint32_t curr_t_ch1_Q16 = 0;

    LoopEvent loop_events_ch2[MAX_BUFFER];
    int num_events_ch2 = 0;
    uint32_t loop_duration_ch2_Q16 = IntToQ16(24);
    uint32_t curr_t_ch2_Q16 = 0;

    // Clock and Tracking
    volatile uint32_t global_tick_count = 0;
    bool use_external_clock = false;
    uint32_t internal_sample_counter = 0;
    
    uint32_t last_seq_step_tick = 0;
    uint32_t last_live_note_tick = 0xFFFFFFFF; 

    int active_live_note = -1;
    uint32_t active_note_start_tick = 0;
    
    uint32_t gate1_close_tick = 0;
    uint32_t gate2_close_tick = 0;
    bool gate1_active = false;
    bool gate2_active = false;

    // Switch Tracking
    uint32_t sw_down_samples = 0;
    bool reverse_ch2 = false;
    bool last_reverse = false;
    bool long_press_triggered = false;

    // handle live loop leakage
    bool CheckLoopModeActive() {
        int k_x = KnobVal(Knob::X);
        int k_y = KnobVal(Knob::Y);
        int n_notes_ch1 = ((k_x * 11) / 4095) + 2;
        int n_notes_ch2 = ((k_y * 11) / 4095) + 2;
        int max_req = (n_notes_ch1 > n_notes_ch2) ? n_notes_ch1 : n_notes_ch2;
        Switch sw_val = SwitchVal();
        
        return (sw_val == Down || sw_val == Middle) && (buffer_count > (max_req + 3));
    }

    // --- MIDI INGESTION ---
    void HandleMIDIClock() {
        use_external_clock = true;
        global_tick_count++;
    }

    void HandleMIDIStart() {
        global_tick_count = 0;
        CloseGates();
    }

    void HandleMIDIStop() {
        CloseGates();
    }

    void HandleMIDINoteOn(uint8_t note, uint8_t velocity) {
        if (velocity == 0) {
            HandleMIDINoteOff(note);
            return;
        }

        // --- 1. ALWAYS Record to Buffer (Background Tracking) ---
        uint32_t delta_ticks = 24; 
        if (last_live_note_tick != 0xFFFFFFFF) {
            delta_ticks = global_tick_count - last_live_note_tick;
            
            // FIX: Cap the maximum recorded silence to 8 seconds (8000 ticks)
            // This prevents massive dead gaps in the loop when you pause to patch cables!
            if (delta_ticks > 8000) {
                delta_ticks = 8000;
            }
        }
        last_live_note_tick = global_tick_count;

        if (active_live_note != -1 && buffer_count > 0) {
            uint32_t dur = global_tick_count - active_note_start_tick;
            note_buffer[buffer_count - 1].duration_ticks = (dur > 0) ? dur : 1;
        }

        if (delta_ticks <= 1 && buffer_count > 0) {
            uint32_t prev_delta = note_buffer[buffer_count - 1].delta_ticks;
            note_buffer[buffer_count - 1] = {prev_delta, note, velocity, 2};
        } else {
            PushToBuffer({delta_ticks, note, velocity, 2});
        }

        active_live_note = note;
        active_note_start_tick = global_tick_count;

        // --- 2. ONLY Trigger Voices if NOT in Loop Mode ---
        if (!CheckLoopModeActive()) {
            TriggerVoice(0, note, velocity);
            TriggerVoice(1, note, velocity);
            gate1_close_tick = global_tick_count + 9999;
            gate2_close_tick = global_tick_count + 9999;
        }
    }

    void HandleMIDINoteOff(uint8_t note) {
        if (note == active_live_note) {
            // ALWAYS update the duration of the note in the buffer
            uint32_t dur = global_tick_count - active_note_start_tick;
            if (buffer_count > 0) {
                note_buffer[buffer_count - 1].duration_ticks = (dur > 0) ? dur : 1;
            }
            
            // ONLY close the physical gates if NOT in Loop Mode
            if (!CheckLoopModeActive()) {
                // Triggers release phase for the envelopes
                gate1_close_tick = global_tick_count;
                gate2_close_tick = global_tick_count;
            }
            active_live_note = -1;
        }
    }

protected:
    // --- AUDIO INTERRUPT LOOP (48kHz) ---
    void ProcessSample() override {
        // 1. HARDWARE CLOCK: Bottom Left Jack (Pulse 1)
        if (PulseIn1RisingEdge()) {
            use_external_clock = true; 
            global_tick_count++;
        }

        // 2. PRECEDENCE: Check Bottom Right Jack (Pulse 2) for a Gate cable
        bool gate_mode_active = Connected(Input::Pulse2);

        // 3. DRAIN MIDI QUEUE
        MIDIMessage msg;
        if (queue_try_remove(&midi_queue, &msg)) {
            if (!gate_mode_active) {
                if (msg.status == 0xF8) HandleMIDIClock();
                else if (msg.status == 0xFA) HandleMIDIStart();
                else if (msg.status == 0xFC) HandleMIDIStop();
                else if ((msg.status & 0xF0) == 0x90) HandleMIDINoteOn(msg.data1, msg.data2);
                else if ((msg.status & 0xF0) == 0x80) HandleMIDINoteOff(msg.data1);
            } else {
                if (msg.status == 0xF8) HandleMIDIClock();
                if (msg.status == 0xFA) HandleMIDIStart();
                if (msg.status == 0xFC) HandleMIDIStop();
            }
        }

        // 4. CV/GATE LOGIC: Pitch from Middle-Left (CV 1), Gate from Bottom-Right (Pulse 2)
        if (gate_mode_active) {
            bool current_gate = PulseIn2();
            if (current_gate && !last_pulse_gate) {
                int note_val = 60 + (CVIn1() / 28); 
                if (note_val < 0) note_val = 0;
                if (note_val > 127) note_val = 127;
                
                last_cv_note = (uint8_t)note_val;
                HandleMIDINoteOn(last_cv_note, 64);
            } 
            else if (!current_gate && last_pulse_gate) {
                HandleMIDINoteOff(last_cv_note);
            }
            last_pulse_gate = current_gate;
        }

        // 5. INTERNAL CLOCK FALLBACK
        if (!use_external_clock) {
            internal_sample_counter++;
            if (internal_sample_counter >= INTERNAL_TICK_SAMPLES) {
                global_tick_count++;
                internal_sample_counter = 0;
            }
        }
        
        // 6. UI and Sequencer Logic
        int k_x = KnobVal(Knob::X);
        int k_y = KnobVal(Knob::Y);
        int n_notes_ch1 = ((k_x * 11) / 4095) + 2;
        int n_notes_ch2 = ((k_y * 11) / 4095) + 2;
        
        int max_req = (n_notes_ch1 > n_notes_ch2) ? n_notes_ch1 : n_notes_ch2;
        bool buffer_ready = (buffer_count > (max_req + 3));

        int main_val = KnobVal(Knob::Main); 
        uint32_t ch2_offset_percent_Q16 = 0;
        uint32_t ch2_speed_Q16 = Q16_ONE;

        if (main_val < 1875) {
            ch2_offset_percent_Q16 = ((1875 - main_val) * Q16_ONE) / 1875;
        } else if (main_val > 2187) {
            ch2_speed_Q16 = Q16_ONE + (((main_val - 2187) * Q16_ONE) / 1908);
        }

        Switch sw_val = SwitchVal();
        bool loop_mode_active = (sw_val == Down || sw_val == Middle) && buffer_ready;

        if (sw_val == Down) {
            if (sw_down_samples == 0) long_press_triggered = false;
            sw_down_samples++;
            if (sw_down_samples >= LATCH_SAMPLES && !long_press_triggered) {
                reverse_ch2 = !reverse_ch2;
                long_press_triggered = true;
            }
        } else {
            if (sw_down_samples > 0 && sw_down_samples < LATCH_SAMPLES && !long_press_triggered) {
                if (loop_duration_ch2_Q16 > 0) curr_t_ch2_Q16 = curr_t_ch1_Q16 % loop_duration_ch2_Q16;
                else curr_t_ch2_Q16 = 0;
            }
            sw_down_samples = 0;
            long_press_triggered = false;
        }

        if (loop_mode_active) {
            ProcessLoopMode(n_notes_ch1, n_notes_ch2, ch2_offset_percent_Q16, ch2_speed_Q16);
        } else {
            // Fix for overlapping live and loop mode
            was_in_loop_mode = false; 

            // switch off reverse mode
            reverse_ch2 = false;
        }

        // =========================================================
        // --- 90% CV / 10% VELOCITY ENVELOPE TIMING ---
        // =========================================================
        
        int32_t raw_cv2 = CVIn2(); 
        
        // Full-Wave Rectifier: Absolute Value
        int32_t abs_cv2 = (raw_cv2 < 0) ? -raw_cv2 : raw_cv2;
        if (abs_cv2 > 2047) abs_cv2 = 2047; // Clamp to max positive
        
        // 90% CV Base
        uint32_t cv_base = (abs_cv2 * 1842) / 2047;
        
        // Add 10% Velocity Offset
        uint32_t timing_1 = cv_base + vca1.vel_timing_offset;
        uint32_t timing_2 = cv_base + vca2.vel_timing_offset;
        if (timing_1 > 2047) timing_1 = 2047;
        if (timing_2 > 2047) timing_2 = 2047;

        // Exponential Curve (step 3 = ~0.45s max time, step ~2000 = ~0.6ms min time)
        vca1.attack_step  = 3 + ((2047 - timing_1) * (2047 - timing_1)) / 2095;
        vca1.release_step = 3 + ((2047 - timing_1) * (2047 - timing_1)) / 2095;
        vca2.attack_step  = 3 + ((2047 - timing_2) * (2047 - timing_2)) / 2095;
        vca2.release_step = 3 + ((2047 - timing_2) * (2047 - timing_2)) / 2095;


        // =========================================================
        // --- DIGITAL VCA & ENVELOPE PROCESSING ---
        // =========================================================

        // 1. Check for Gate Closures
        if (gate1_active && global_tick_count >= gate1_close_tick) {
            vca1.state = RELEASE;
            PulseOut1(false);
            gate1_active = false;
        }
        if (gate2_active && global_tick_count >= gate2_close_tick) {
            vca2.state = RELEASE;
            PulseOut2(false);
            gate2_active = false;
        }

        // 2. Process VCA 1
        if (vca1.state == ATTACK) {
            if (vca1.current_level_Q16 < vca1.target_level_Q16) {
                // If target is Louder: Slew UP smoothly
                vca1.current_level_Q16 += vca1.attack_step;
                if (vca1.current_level_Q16 >= vca1.target_level_Q16) {
                    vca1.current_level_Q16 = vca1.target_level_Q16; // Hold at sustain
                }
            } else if (vca1.current_level_Q16 > vca1.target_level_Q16) {
                // ANTI-CLICK FIX: If target is Softer: Slew DOWN smoothly
                if (vca1.current_level_Q16 > vca1.target_level_Q16 + vca1.attack_step) {
                    vca1.current_level_Q16 -= vca1.attack_step;
                } else {
                    vca1.current_level_Q16 = vca1.target_level_Q16; // Reached target
                }
            }
        } else if (vca1.state == RELEASE) {
            if (vca1.current_level_Q16 > vca1.release_step) {
                vca1.current_level_Q16 -= vca1.release_step;
            } else {
                vca1.current_level_Q16 = 0;
                vca1.state = IDLE;
            }
        }

        // 3. Process VCA 2
        if (vca2.state == ATTACK) {
            if (vca2.current_level_Q16 < vca2.target_level_Q16) {
                vca2.current_level_Q16 += vca2.attack_step;
                if (vca2.current_level_Q16 >= vca2.target_level_Q16) {
                    vca2.current_level_Q16 = vca2.target_level_Q16;
                }
            } else if (vca2.current_level_Q16 > vca2.target_level_Q16) {
                if (vca2.current_level_Q16 > vca2.target_level_Q16 + vca2.attack_step) {
                    vca2.current_level_Q16 -= vca2.attack_step;
                } else {
                    vca2.current_level_Q16 = vca2.target_level_Q16;
                }
            }
        } else if (vca2.state == RELEASE) {
            if (vca2.current_level_Q16 > vca2.release_step) {
                vca2.current_level_Q16 -= vca2.release_step;
            } else {
                vca2.current_level_Q16 = 0;
                vca2.state = IDLE;
            }
        }

        // 4. Multiply Incoming Audio by Envelope Level
        int16_t raw_audio_1 = AudioIn1(); 
        int16_t raw_audio_2 = AudioIn2(); 
        
        int32_t shaped_audio_1 = ((int32_t)raw_audio_1 * (int32_t)vca1.current_level_Q16) >> 16;
        int32_t shaped_audio_2 = ((int32_t)raw_audio_2 * (int32_t)vca2.current_level_Q16) >> 16;
        
        // 5. Send to physical outputs
        AudioOut1((int16_t)shaped_audio_1);
        AudioOut2((int16_t)shaped_audio_2);
    }

private:
    void PushToBuffer(NoteEvent ev) {
        if (buffer_count < MAX_BUFFER) {
            note_buffer[buffer_count++] = ev;
        } else {
            for (int i = 1; i < MAX_BUFFER; i++) note_buffer[i - 1] = note_buffer[i];
            note_buffer[MAX_BUFFER - 1] = ev;
        }
    }

    void BuildTimeline(int n_notes, bool reverse, LoopEvent* events, int& num_events, uint32_t& duration_Q16) {
        num_events = 0;
        uint32_t current_t_Q16 = 0;
        
        // SNAPSHOT FIX: Read exclusively from the frozen snapshot array
        int start_idx = snapshot_buffer_count - n_notes - 1;
        if (start_idx < 0) start_idx = 0;
        int end_idx = snapshot_buffer_count - 1;
        if (end_idx < 0) end_idx = 0;

        if (!reverse) {
            for (int i = start_idx; i < end_idx; i++) {
                current_t_Q16 += IntToQ16(snapshot_buffer[i].delta_ticks);
                events[num_events++] = {
                    current_t_Q16, 
                    snapshot_buffer[i].note, 
                    snapshot_buffer[i].velocity, 
                    IntToQ16(snapshot_buffer[i].duration_ticks)
                };
            }
        } else {
            for (int i = end_idx - 1; i >= start_idx; i--) {
                current_t_Q16 += IntToQ16(snapshot_buffer[i].delta_ticks);
                events[num_events++] = {
                    current_t_Q16, 
                    snapshot_buffer[i].note, 
                    snapshot_buffer[i].velocity, 
                    IntToQ16(snapshot_buffer[i].duration_ticks)
                };
            }
        }
        duration_Q16 = (current_t_Q16 > 0) ? current_t_Q16 : IntToQ16(24);
    }

    void CheckTriggers(uint32_t start_t_Q16, uint32_t end_t_Q16, LoopEvent* events, int num_events, uint32_t duration_Q16, int channel, uint32_t speed_Q16) {
        if (start_t_Q16 < end_t_Q16) {
            for (int i = 0; i < num_events; i++) {
                if (events[i].t_Q16 > start_t_Q16 && events[i].t_Q16 <= end_t_Q16) FireEvent(channel, events[i], speed_Q16);
            }
        } else {
            for (int i = 0; i < num_events; i++) {
                if (events[i].t_Q16 > start_t_Q16 && events[i].t_Q16 <= duration_Q16) FireEvent(channel, events[i], speed_Q16);
                if (events[i].t_Q16 <= end_t_Q16) FireEvent(channel, events[i], speed_Q16);
            }
        }
    }

    void FireEvent(int channel, const LoopEvent& ev, uint32_t speed_Q16) {
        TriggerVoice(channel, ev.note, ev.velocity);
        uint32_t adj_dur_ticks = (uint32_t)(((uint64_t)ev.duration_Q16 << 16) / speed_Q16) >> 16;
        if (adj_dur_ticks == 0) adj_dur_ticks = 1;
        if (channel == 0) gate1_close_tick = global_tick_count + adj_dur_ticks;
        if (channel == 1) gate2_close_tick = global_tick_count + adj_dur_ticks;
    }

    void ProcessLoopMode(int n_notes_ch1, int n_notes_ch2, uint32_t ch2_offset_percent_Q16, uint32_t ch2_speed_Q16) {
        if (!was_in_loop_mode) {
            last_seq_step_tick = global_tick_count;
            was_in_loop_mode = true;
            
            // SNAPSHOT FIX: Lock the snapshot buffer so background playing doesn't ruin rebuilds
            snapshot_buffer_count = buffer_count;
            for (int i = 0; i < buffer_count; i++) {
                snapshot_buffer[i] = note_buffer[i];
                
                // FIX: If the note is currently being held when the switch is flipped, 
                // calculate its real duration up to this exact moment. 
                // Otherwise, the VCA will only open for the 2ms default and output silence!
                if (i == buffer_count - 1 && active_live_note != -1) {
                    uint32_t current_dur = global_tick_count - active_note_start_tick;
                    snapshot_buffer[i].duration_ticks = (current_dur > 0) ? current_dur : 1;
                }
            }

            last_n_notes_ch1 = n_notes_ch1;
            BuildTimeline(n_notes_ch1, false, loop_events_ch1, num_events_ch1, loop_duration_ch1_Q16);
            curr_t_ch1_Q16 = 0;
            last_n_notes_ch2 = n_notes_ch2;
            last_reverse = reverse_ch2;
            BuildTimeline(n_notes_ch2, reverse_ch2, loop_events_ch2, num_events_ch2, loop_duration_ch2_Q16);
            curr_t_ch2_Q16 = 0;
        }

        int dt_ticks = global_tick_count - last_seq_step_tick;
        last_seq_step_tick = global_tick_count;

        if (dt_ticks > 0) {
            if (num_events_ch1 > 0) {
                uint32_t v_last_t1_Q16 = curr_t_ch1_Q16;
                curr_t_ch1_Q16 = (curr_t_ch1_Q16 + IntToQ16(dt_ticks)) % loop_duration_ch1_Q16;
                CheckTriggers(v_last_t1_Q16, curr_t_ch1_Q16, loop_events_ch1, num_events_ch1, loop_duration_ch1_Q16, 0, Q16_ONE);
                if (curr_t_ch1_Q16 < v_last_t1_Q16 && n_notes_ch1 != last_n_notes_ch1) {
                    last_n_notes_ch1 = n_notes_ch1;
                    BuildTimeline(n_notes_ch1, false, loop_events_ch1, num_events_ch1, loop_duration_ch1_Q16);
                }
            }
            if (num_events_ch2 > 0) {
                uint32_t base_last_t2_Q16 = curr_t_ch2_Q16;
                uint32_t advanced_ticks_Q16 = dt_ticks * ch2_speed_Q16;
                curr_t_ch2_Q16 = (curr_t_ch2_Q16 + advanced_ticks_Q16) % loop_duration_ch2_Q16;
                uint32_t offset_ticks_Q16 = MulQ16(loop_duration_ch2_Q16, ch2_offset_percent_Q16);
                uint32_t actual_last_t2_Q16 = (base_last_t2_Q16 + offset_ticks_Q16) % loop_duration_ch2_Q16;
                uint32_t actual_curr_t2_Q16 = (curr_t_ch2_Q16 + offset_ticks_Q16) % loop_duration_ch2_Q16;
                CheckTriggers(actual_last_t2_Q16, actual_curr_t2_Q16, loop_events_ch2, num_events_ch2, loop_duration_ch2_Q16, 1, ch2_speed_Q16);
                if (curr_t_ch2_Q16 < base_last_t2_Q16 && (n_notes_ch2 != last_n_notes_ch2 || reverse_ch2 != last_reverse)) {
                    last_n_notes_ch2 = n_notes_ch2;
                    last_reverse = reverse_ch2;
                    BuildTimeline(n_notes_ch2, reverse_ch2, loop_events_ch2, num_events_ch2, loop_duration_ch2_Q16);
                }
            }
        }
    }

    void TriggerVoice(int channel, uint8_t note, uint8_t velocity) {
        if (channel == 0) {
            CVOut1MIDINote(note); 
            vca1.target_level_Q16 = ((uint32_t)velocity * Q16_ONE) / 127;
            vca1.vel_timing_offset = ((127 - velocity) * 204) / 127; 
            vca1.state = ATTACK;
            PulseOut1(true);
            gate1_active = true;
        } else {
            CVOut2MIDINote(note);
            vca2.target_level_Q16 = ((uint32_t)velocity * Q16_ONE) / 127;
            vca2.vel_timing_offset = ((127 - velocity) * 204) / 127; 
            vca2.state = ATTACK;
            PulseOut2(true);
            gate2_active = true;
        }
    }

    void CloseGates() {
        // Now just instantly shifts envelopes to release phase
        gate1_close_tick = global_tick_count;
        gate2_close_tick = global_tick_count;
    }
};

#endif