(
var customPath = nil;
var loadAll = false;

// 1. Parse arguments SAFELY 
if (thisProcess.argv.notNil) {
    // Changed |arg| to |item| because 'arg' is a reserved keyword
    thisProcess.argv.do({ |item|
        if (item == "--all") {
            loadAll = true;
        } {
            // Assume anything else is the custom path
            customPath = item;
        };
    });
};

s.quit; 

s.options.numInputBusChannels = 0;
s.options.numOutputBusChannels = 2;
s.options.memSize = 8192 * 32;
s.options.numBuffers = 1024 * 256;

s.waitForBoot({
    ~dirt = SuperDirt(2, s);
    
    // Logic for loading samples
    if (loadAll) {
        "Flag --all detected. Loading standard Tidal samples...".postln;
        ~dirt.loadSoundFiles(); // Loads defaults
    };

    if (customPath.notNil) {
        ("Loading custom samples from: " + customPath).postln;
        ~dirt.loadSoundFiles(customPath);
    };
    
    // Fallback: if no path and no flag, load defaults anyway so it's not empty
    if (loadAll.not && customPath.isNil) {
        "No arguments provided. Loading default samples...".postln;
        ~dirt.loadSoundFiles();
    };

    s.sync;
    ~dirt.start(57120, 0 ! 12);
    "--------------------------------------".postln;
    "Tidal is ready! Booted successfully.".postln;
    "--------------------------------------".postln;
});
)
