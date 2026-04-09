// Fixes sample rate mismatch by disabling audio inputs and setting stereo output
s.options.numInputBusChannels = 0;
s.options.numOutputBusChannels = 2;

s.waitForBoot {
    // 1. Initialize SuperDirt
    ~dirt = SuperDirt(2, s); // 2 audio channels
    ~dirt.loadSoundFiles;    // Load default Tidal samples
    s.sync;
    ~dirt.start(57120, 0 ! 12);

    // 2. Initialize MIDI Client
    MIDIClient.init;
    
    // Give the MIDI client a fraction of a second to populate devices
    0.5.wait;

    // 3. Connect to the macOS IAC Driver (which Logic Pro listens to)
    ~midiOut = MIDIOut.newByName("IAC Driver", "Bus 1");
    
    // Optional: Adjust latency. 0.0 keeps timing tight with Tidal's scheduler
    ~midiOut.latency = 0.0; 

    // 4. Register the MIDI connection in SuperDirt
    // This allows you to trigger it in Tidal using: s "logic"
    ~dirt.soundLibrary.addMIDI(\logic, ~midiOut);

    "\n*** SuperDirt is ready! ***".postln;
    "*** Logic Pro MIDI (IAC Driver) added as 'logic' ***\n".postln;
}
