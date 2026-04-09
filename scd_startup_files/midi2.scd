s.options.sampleRate = 44100;


SuperDirt.start;

s.waitForBoot {
~dirt = SuperDirt(2, s);

~dirt.start(57120, 0 ! 12);

MIDIClient.init;

~surgeMIDIout = MIDIOut.newByName("IAC Driver", "Surge");

~surgeMIDIout.latency = 0.0;
~dirt.soundLibrary.addMIDI(\sur, ~surgeMIDIout);


~dexMIDIout = MIDIOut.newByName("IAC Driver", "Dexed");

~dexMIDIout.latency = 0.0;
~dirt.soundLibrary.addMIDI(\dex, ~dexMIDIout);

};