#ifndef TIMESHIFTLOOPER_H
#define TIMESHIFTLOOPER_H

#include "ComputerCard.h"
#include "pico/util/queue.h"
#include <stdint.h>
#include <cmath>

// 1. Move the struct here so both main.cpp and the class can see it
struct MIDIMessage {
    uint8_t status;
    uint8_t data1;
    uint8_t data2;
};

// 2. Declare the queue as extern AT GLOBAL SCOPE (outside the class)
extern queue_t midi_queue;

// --- HELPER STRUCTS ---
struct NoteEvent {
    uint32_t delta_ticks;
    uint8_t note;
    uint8_t velocity;
    uint32_t duration_ticks;
};

struct LoopEvent {
    float t;
    uint8_t note;
    uint8_t velocity;
    uint32_t duration;
};

// --- CORE LOOPER CLASS ---
class TimeshiftLooper : public ComputerCard {
public:
    static constexpr int MAX_BUFFER = 30;
    static constexpr uint32_t LATCH_SAMPLES = 24000; // 0.5 seconds @ 48kHz
    static constexpr uint32_t INTERNAL_TICK_SAMPLES = 1000; // ~120 BPM at 24 PPQN

    // State Variables
    NoteEvent note_buffer[MAX_BUFFER];
    int buffer_count = 0;

    bool was_in_loop_mode = false;
    int last_n_notes_ch1 = 0;
    int last_n_notes_ch2 = 0;

    // Timeline Variables
    LoopEvent loop_events_ch1[MAX_BUFFER];
    int num_events_ch1 = 0;
    float loop_duration_ch1 = 24.0f;
    float curr_t_ch1 = 0.0f;

    LoopEvent loop_events_ch2[MAX_BUFFER];
    int num_events_ch2 = 0;
    float loop_duration_ch2 = 24.0f;
    float curr_t_ch2 = 0.0f;

    // Clock and Tracking
    volatile uint32_t global_tick_count = 0;
    bool use_external_clock = false;
    uint32_t internal_sample_counter = 0;
    
    uint32_t last_seq_step_tick = 0;
    uint32_t last_live_note_tick = 0xFFFFFFFF; // Equivalent to -1

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

    TimeshiftLooper() {
        UpdateControls();
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

        if (was_in_loop_mode) {
            CloseGates();
            was_in_loop_mode = false;
        }

        uint32_t delta_ticks = 24; 
        if (last_live_note_tick != 0xFFFFFFFF) {
            delta_ticks = global_tick_count - last_live_note_tick;
        }
        last_live_note_tick = global_tick_count;

        // Legato interrupt
        if (active_live_note != -1 && buffer_count > 0) {
            uint32_t dur = global_tick_count - active_note_start_tick;
            note_buffer[buffer_count - 1].duration_ticks = (dur > 0) ? dur : 1;
        }

        // Chord filter (~20ms / 1 tick)
        if (delta_ticks <= 1 && buffer_count > 0) {
            uint32_t prev_delta = note_buffer[buffer_count - 1].delta_ticks;
            note_buffer[buffer_count - 1] = {prev_delta, note, velocity, 2};
        } else {
            PushToBuffer({delta_ticks, note, velocity, 2});
        }

        active_live_note = note;
        active_note_start_tick = global_tick_count;

        TriggerVoice(0, note, velocity);
        TriggerVoice(1, note, velocity);

        gate1_close_tick = global_tick_count + 9999;
        gate2_close_tick = global_tick_count + 9999;
    }

    void HandleMIDINoteOff(uint8_t note) {
        if (note == active_live_note) {
            uint32_t dur = global_tick_count - active_note_start_tick;
            if (buffer_count > 0) {
                note_buffer[buffer_count - 1].duration_ticks = (dur > 0) ? dur : 1;
            }
            CloseGates();
            active_live_note = -1;
        }
    }

protected:
    // --- AUDIO INTERRUPT LOOP (48kHz) ---
    void ProcessSample() override {
        // 1. Drain ONLY ONE message per sample to keep the interrupt incredibly fast
        MIDIMessage msg;
        if (queue_try_remove(&midi_queue, &msg)) {
            if (msg.status == 0xF8) HandleMIDIClock();
            else if (msg.status == 0xFA) HandleMIDIStart();
            else if (msg.status == 0xFC) HandleMIDIStop();
            else if ((msg.status & 0xF0) == 0x90) HandleMIDINoteOn(msg.data1, msg.data2);
            else if ((msg.status & 0xF0) == 0x80) HandleMIDINoteOff(msg.data1);
        }

        // 2. Fallback Internal Clock
        if (!use_external_clock) {
            internal_sample_counter++;
            if (internal_sample_counter >= INTERNAL_TICK_SAMPLES) {
                global_tick_count++;
                internal_sample_counter = 0;
            }
        }

        // 3. Read UI State
        int k_x = KnobVal(Knob::X);
        int k_y = KnobVal(Knob::Y);
        int n_notes_ch1 = ((k_x * 11) / 4095) + 2;
        int n_notes_ch2 = ((k_y * 11) / 4095) + 2;
        
        int max_req = (n_notes_ch1 > n_notes_ch2) ? n_notes_ch1 : n_notes_ch2;
        bool buffer_ready = (buffer_count > (max_req + 3));

        // 4. Big Knob Logic (Phase vs Speed)
        int main_val = KnobVal(Knob::Main); // 0 - 4095
        float ch2_offset_percent = 0.0f;
        float ch2_speed = 1.0f;

        if (main_val < 1875) {
            ch2_offset_percent = (1875.0f - main_val) / 1875.0f;
        } else if (main_val > 2187) {
            ch2_speed = 1.0f + ((main_val - 2187) / 1908.0f);
        }

        // 5. Switch Logic (Latch & Sync)
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
            if (sw_down_samples > 0) {
                if (sw_down_samples < LATCH_SAMPLES && !long_press_triggered) {
                    // Quick Flick: Sync Timelines
                    if (loop_duration_ch2 > 0) {
                        curr_t_ch2 = fmod(curr_t_ch1, loop_duration_ch2);
                    } else {
                        curr_t_ch2 = 0.0f;
                    }
                }
            }
            sw_down_samples = 0;
            long_press_triggered = false;
        }

        // 6. Run Sequencer
        if (loop_mode_active) {
            ProcessLoopMode(n_notes_ch1, n_notes_ch2, ch2_offset_percent, ch2_speed);
        }

        // 7. Check Gate Timeouts
        if (gate1_active && global_tick_count >= gate1_close_tick) {
            PulseOut1(false);
            gate1_active = false;
        }
        if (gate2_active && global_tick_count >= gate2_close_tick) {
            PulseOut2(false);
            gate2_active = false;
        }
    }

private:
    // --- INTERNAL HELPERS ---
    void PushToBuffer(NoteEvent ev) {
        if (buffer_count < MAX_BUFFER) {
            note_buffer[buffer_count++] = ev;
        } else {
            // Shift array left
            for (int i = 1; i < MAX_BUFFER; i++) {
                note_buffer[i - 1] = note_buffer[i];
            }
            note_buffer[MAX_BUFFER - 1] = ev;
        }
    }

    void BuildTimeline(int n_notes, bool reverse, LoopEvent* events, int& num_events, float& duration) {
        num_events = 0;
        float current_t = 0;
        
        int start_idx = buffer_count - n_notes - 1;
        if (start_idx < 0) start_idx = 0;
        int end_idx = buffer_count - 1;

        if (!reverse) {
            for (int i = start_idx; i < end_idx; i++) {
                current_t += note_buffer[i].delta_ticks;
                events[num_events++] = {current_t, note_buffer[i].note, note_buffer[i].velocity, note_buffer[i].duration_ticks};
            }
        } else {
            // Reverse extraction
            for (int i = end_idx - 1; i >= start_idx; i--) {
                current_t += note_buffer[i].delta_ticks;
                events[num_events++] = {current_t, note_buffer[i].note, note_buffer[i].velocity, note_buffer[i].duration_ticks};
            }
        }
        duration = (current_t > 0) ? current_t : 24.0f;
    }

    void CheckTriggers(float start_t, float end_t, LoopEvent* events, int num_events, float duration, int channel, float speed) {
        if (start_t < end_t) {
            for (int i = 0; i < num_events; i++) {
                if (events[i].t > start_t && events[i].t <= end_t) {
                    FireEvent(channel, events[i], speed);
                }
            }
        } else {
            // Wrap-around boundary
            for (int i = 0; i < num_events; i++) {
                if (events[i].t > start_t && events[i].t <= duration) {
                    FireEvent(channel, events[i], speed);
                }
                if (events[i].t >= 0 && events[i].t <= end_t) {
                    FireEvent(channel, events[i], speed);
                }
            }
        }
    }

    void FireEvent(int channel, const LoopEvent& ev, float speed) {
        TriggerVoice(channel, ev.note, ev.velocity);
        uint32_t adj_dur = ev.duration / speed;
        if (channel == 0) gate1_close_tick = global_tick_count + adj_dur;
        if (channel == 1) gate2_close_tick = global_tick_count + adj_dur;
    }

    void ProcessLoopMode(int n_notes_ch1, int n_notes_ch2, float ch2_offset_percent, float ch2_speed) {
        if (!was_in_loop_mode) {
            last_seq_step_tick = global_tick_count;
            was_in_loop_mode = true;

            last_n_notes_ch1 = n_notes_ch1;
            BuildTimeline(n_notes_ch1, false, loop_events_ch1, num_events_ch1, loop_duration_ch1);
            curr_t_ch1 = 0.0f;

            last_n_notes_ch2 = n_notes_ch2;
            last_reverse = reverse_ch2;
            BuildTimeline(n_notes_ch2, reverse_ch2, loop_events_ch2, num_events_ch2, loop_duration_ch2);
            curr_t_ch2 = 0.0f;
        }

        int dt_ticks = global_tick_count - last_seq_step_tick;
        last_seq_step_tick = global_tick_count;

        if (dt_ticks > 0) {
            // --- CHANNEL 1 ---
            if (num_events_ch1 > 0) {
                float v_last_t1 = curr_t_ch1;
                curr_t_ch1 = fmod((curr_t_ch1 + dt_ticks), loop_duration_ch1);
                
                CheckTriggers(v_last_t1, curr_t_ch1, loop_events_ch1, num_events_ch1, loop_duration_ch1, 0, 1.0f);

                // Rebuild boundary
                if (curr_t_ch1 < v_last_t1 && n_notes_ch1 != last_n_notes_ch1) {
                    last_n_notes_ch1 = n_notes_ch1;
                    BuildTimeline(n_notes_ch1, false, loop_events_ch1, num_events_ch1, loop_duration_ch1);
                }
            }

            // --- CHANNEL 2 ---
            if (num_events_ch2 > 0) {
                float base_last_t2 = curr_t_ch2;
                curr_t_ch2 = fmod((curr_t_ch2 + (dt_ticks * ch2_speed)), loop_duration_ch2);
                
                float offset_ticks = loop_duration_ch2 * ch2_offset_percent;
                float actual_last_t2 = fmod((base_last_t2 + offset_ticks), loop_duration_ch2);
                float actual_curr_t2 = fmod((curr_t_ch2 + offset_ticks), loop_duration_ch2);

                CheckTriggers(actual_last_t2, actual_curr_t2, loop_events_ch2, num_events_ch2, loop_duration_ch2, 1, ch2_speed);

                // Rebuild boundary
                if (curr_t_ch2 < base_last_t2 && (n_notes_ch2 != last_n_notes_ch2 || reverse_ch2 != last_reverse)) {
                    last_n_notes_ch2 = n_notes_ch2;
                    last_reverse = reverse_ch2;
                    BuildTimeline(n_notes_ch2, reverse_ch2, loop_events_ch2, num_events_ch2, loop_duration_ch2);
                }
            }
        }
    }

    void TriggerVoice(int channel, uint8_t note, uint8_t velocity) {
        if (channel == 0) {
            CVOut1MIDINote(note); // Automatically uses EEPROM calibration to spit out V/Oct
            AudioOut1((velocity * 2047) / 127); // Map 0-127 MIDI to DC-coupled Audio Out 
            PulseOut1(true);
            gate1_active = true;
        } else {
            CVOut2MIDINote(note);
            AudioOut2((velocity * 2047) / 127);
            PulseOut2(true);
            gate2_active = true;
        }
    }

    void CloseGates() {
        PulseOut1(false);
        PulseOut2(false);
        gate1_active = false;
        gate2_active = false;
    }
};

#endif