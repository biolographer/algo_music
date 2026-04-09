(
// 1. FORCE THE OUTPUT DEVICE
// This ensures SC doesn't trigger the AirPods microphone/24kHz mode
Server.default.options.outDevice_("AirPods Pro"); 
Server.default.options.inDevice_(nil); // Explicitly disable input device

// 2. SERVER RESOURCES
s.options.numInputBusChannels = 0;
s.options.numOutputBusChannels = 2;
s.options.memSize = 262144;      
s.options.numWireBufs = 256;     
s.options.sampleRate = 48000;    // Force SC to stay at 48k

s.waitForBoot {
    // 3. INITIALIZE SUPERDIRT
    ~dirt = SuperDirt(2, s); 
    ~dirt.loadSoundFiles;    
    s.sync;
    ~dirt.start(57120, 0 ! 12); 

    // 4. INITIALIZE MIDI
    MIDIClient.init;
    0.5.wait;
    
    ~midiOut = MIDIOut.newByName("IAC Driver", "Bus 1");
    ~midiOut.latency = 0.0; 
    ~dirt.soundLibrary.addMIDI(\logic, ~midiOut);

    "\n*** SETUP COMPLETE - CHECKING SAMPLE RATE ***".postln;
    ("Current Sample Rate: " + s.sampleRate).postln;
};
)
