// Fixes sample rate mismatch by disabling audio inputs and setting stereo output
s.options.numInputBusChannels = 0;
s.options.numOutputBusChannels = 2;

s.waitForBoot {
    // SuperCollider requires variables to be declared at the top of the block
    var activeNotes = List.new; 
    var osc = NetAddr.new("127.0.0.1", 6010); // Tidal's default listening port
    
    // ---------------------------------------------------------
    // 1. INITIALIZE SUPERDIRT
    // ---------------------------------------------------------
    ~dirt = SuperDirt(2, s); // 2 audio channels
    ~dirt.loadSoundFiles;    // Load default Tidal samples
    s.sync;
    ~dirt.start(57120, 0 ! 12);

    // ---------------------------------------------------------
    // 2. INITIALIZE MIDI (IN AND OUT)
    // ---------------------------------------------------------
    MIDIClient.init;
    
    // Give the MIDI client a fraction of a second to populate devices
    0.5.wait;
    
    // Connect all incoming MIDI devices (for your MIDI keyboard)
    MIDIIn.connectAll;

    // ---------------------------------------------------------
    // 3. SETUP MIDI OUT (To Logic Pro)
    // ---------------------------------------------------------
    // Connect to the macOS IAC Driver (which Logic Pro listens to)
    ~midiOut = MIDIOut.newByName("IAC Driver", "Bus 1");
    
    // Optional: Adjust latency. 0.0 keeps timing tight with Tidal's scheduler
    ~midiOut.latency = 0.0; 

    // Register the MIDI connection in SuperDirt
    // This allows you to trigger it in Tidal using: s "logic"
    ~dirt.soundLibrary.addMIDI(\logic, ~midiOut);

    // ---------------------------------------------------------
    // 4. SETUP MIDI IN -> OSC CONTROLLER (From Keyboard to Tidal)
    // ---------------------------------------------------------
    // Clear previous MIDI functions if re-evaluating to prevent duplicates
    if (~stopChordMidi != nil, { ~stopChordMidi.value; });

    ~noteOn = MIDIFunc.noteOn({ |val, num, chan, src|
        var tidalNote = num - 60; // Convert to Tidal's Middle C relative pitch
        
        // Add the note to our list if it isn't already there
        if(activeNotes.includes(tidalNote).not, {
            activeNotes.add(tidalNote);
        });
        
        // Send the list as a formatted string: e.g., "[0,4,7]"
        osc.sendMsg("/ctrl", "keyChord", "[" ++ activeNotes.join(",") ++ "]");
    });

    ~noteOff = MIDIFunc.noteOff({ |val, num, chan, src|
        var tidalNote = num - 60;
        
        activeNotes.remove(tidalNote);
        
        // Only update Tidal if you are still holding at least one key.
        // This lets your last chord "ring out" when you lift your hands.
        if(activeNotes.size > 0, {
            osc.sendMsg("/ctrl", "keyChord", "[" ++ activeNotes.join(",") ++ "]");
        });
    });

    // Store cleanup function for the MIDI listener
    ~stopChordMidi = { ~noteOn.free; ~noteOff.free; };

    // ---------------------------------------------------------
    // 5. CONFIRMATION MESSAGES
    // ---------------------------------------------------------
    "\n*** SuperDirt is ready! ***".postln;
    "*** Logic Pro MIDI (IAC Driver) added as 'logic' ***".postln;
    "*** MIDI Keyboard controller active on 'keyChord' ***\n".postln;
}