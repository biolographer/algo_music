#include "TimeshiftLooper.h"
#include "tusb.h"
#include "pico/multicore.h"
#include "pico/stdlib.h"

// The queue and pointer are defined here
queue_t midi_queue;
TimeshiftLooper* looper = nullptr; 

void core1_entry() {
    // Core 1 enters the high-speed audio loop
    looper->Run(); 
}

int main() {
    // board_init();
    stdio_init_all();
    tusb_init();

    // 1. Initialize the thread-safe queue
    queue_init(&midi_queue, sizeof(MIDIMessage), 32);

    // 2. Create the looper (Hardware setup happens here)
    looper = new TimeshiftLooper();

    // 3. Launch the audio engine on the second core
    multicore_launch_core1(core1_entry);

    // 4. Core 0 handles USB and MIDI background tasks
    while (1) {
        tud_task(); 
        
        if (tud_midi_available()) {
            uint8_t packet[4];
            while (tud_midi_packet_read(packet)) {
                MIDIMessage msg = { packet[1], packet[2], packet[3] };
                
                // Pushing to the queue is thread-safe! 
                // Core 1 will pick this up in its next ProcessSample() call.
                queue_try_add(&midi_queue, &msg);
            }
        }
    }
}