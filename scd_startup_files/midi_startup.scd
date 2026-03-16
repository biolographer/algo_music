SuperDirt.start;

MIDIClient.init;

~dexed = MIDIOut.newByName("IAC Driver", "Bus 1");
~dexed.latency = 0;
~dirt.soundLibrary.addMIDI(\dex, ~dexed);