(
// 1. Clean up any previous server instances
s.quit; 

// 2. Configure options BEFORE booting
s.options.numInputBusChannels = 0;    // Fixes the sample rate mismatch
s.options.numOutputBusChannels = 2;
s.options.memSize = 8192 * 32;       // 256MB - safe for 8GB RAM
s.options.numBuffers = 1024 * 256;   // Plenty of slots for samples

// 3. Boot and Start SuperDirt
s.waitForBoot({
    ~dirt = SuperDirt(2, s);
    ~dirt.loadSoundFiles();
    s.sync;
    ~dirt.start(57120, 0 ! 12);
    "--------------------------------------".postln;
    "Tidal is ready!".postln;
    "--------------------------------------".postln;
});
)
