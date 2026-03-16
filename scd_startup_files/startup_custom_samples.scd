(
var samplePath;

// USE thisProcess.argv instead of Process.argv
samplePath = thisProcess.argv[0]; 

s.quit; 

s.options.numInputBusChannels = 0;
s.options.numOutputBusChannels = 2;
s.options.memSize = 8192 * 32;
s.options.numBuffers = 1024 * 256;

s.waitForBoot({
    ~dirt = SuperDirt(2, s);
    
    if(samplePath.isNil) {
        "No path provided. Loading default Tidal samples...".postln;
        ~dirt.loadSoundFiles();
    } {
        ("Loading custom samples from: " + samplePath).postln;
        ~dirt.loadSoundFiles(samplePath);
    };

    s.sync;
    ~dirt.start(57120, [0, 0]);
    "Tidal is ready with custom path support.".postln;
});
)
