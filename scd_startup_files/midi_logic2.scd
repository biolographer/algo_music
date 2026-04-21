(
s.quit; // Always start fresh to apply options

// 1. Configure Server
s.options.numInputBusChannels = 0;
s.options.numOutputBusChannels = 2;
s.options.memSize = 8192 * 32;
s.options.numBuffers = 1024 * 256;

s.waitForBoot {
    // 2. Initialize SuperDirt
    ~dirt = SuperDirt(2, s);

    // Explicitly load default samples - you can add a path inside () if they are custom
    ~dirt.loadSoundFiles();
    s.sync;

    // Start with 12 orbits (standard for Tidal)
    ~dirt.start(57120, 0 ! 12);
    s.sync;

    // 3. MIDI Setup
    MIDIClient.init;
    0.5.wait;

    // Use an if-statement to ensure the MIDI destination exists before assigning
    try {
        ~midiOut = MIDIOut.newByName("IAC Driver", "Bus 1");
        ~midiOut.latency = 0.0;
        ~dirt.soundLibrary.addMIDI(\logic, ~midiOut);
        "*** MIDI 'logic' (IAC Driver) initialized ***".postln;
    } {
        "*** WARNING: IAC Driver Bus 1 not found ***".postln;
    };

    "\n*** SuperDirt & Tidal are ready! ***".postln;
}
)
