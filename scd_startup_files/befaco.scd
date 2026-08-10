(
MIDIClient.init;
~midiOut = MIDIOut.newByName("MIDIThing2", "MIDIThing2");
//~midiOut = MIDIOut.newByName("IAC Driver", "Bus 1");
~midiOut.latency = 0;

// 1. GUI Setup - Widened for side-by-side layout
~win = Window("Befaco MIDI Thing V2 - Multi-Voice Controller", Rect(100, 100, 700, 700));
~scroll = ScrollView(~win, Rect(0, 0, 700, 700)).hasHorizontalScroller_(false);
~container = View(~scroll, Rect(0, 0, 680, 800)); // Container width 680 fits exactly two 320px boxes
~container.decorator = FlowLayout(~container.bounds, 10@10, 15@15);

// 2. Helper to create a grouped ADSR box
~createVoiceSet = { arg voiceName, startChan;
    var chan = startChan;

    // Create a sub-box for this specific ADSR
    var comp = CompositeView(~container, 320@180);
    comp.background_(Color.gray(0.9)); // Light gray background for grouping
    comp.decorator = FlowLayout(comp.bounds, 10@10, 5@5);

    // Header & Channel Selector (Side by side)
    StaticText(comp, 120@20).string_(voiceName).font_(Font("Helvetica", 14, true));
    StaticText(comp, 80@20).string_("Channel:").align_(\right);
    PopUpMenu(comp, 80@20)
        .items_(Array.fill(16, { arg i; (i+1).asString }))
        .value_(startChan)
        .action_({ arg menu; chan = menu.value; });

    // Fader factory tied to this specific box
    ~makeFader = { arg labelName, ccNum, initVal;
        EZSlider(comp, 300@25, labelName, ControlSpec(0, 127, \lin, 1, 0), { arg sl;
            ~midiOut.control(chan, ccNum, sl.value.asInteger);
        }, initVal, labelWidth: 60).doAction;
    };

    // ADSR Faders
    ~makeFader.value("Attack", 73, 10);
    ~makeFader.value("Decay", 75, 20);
    ~makeFader.value("Sustain", 79, 100);
    ~makeFader.value("Release", 72, 20);
};

// 3. Helper to create a grouped LFO box
~createLFOSet = { arg lfoName, startChan;
    var chan = startChan;

    // Create a sub-box for this specific LFO
    var comp = CompositeView(~container, 320@110);
    comp.background_(Color.gray(0.85)); // Slightly darker gray for LFOs
    comp.decorator = FlowLayout(comp.bounds, 10@10, 5@5);

    // Header & Channel Selector
    StaticText(comp, 120@20).string_(lfoName).font_(Font("Helvetica", 14, true));
    StaticText(comp, 80@20).string_("Channel:").align_(\right);
    PopUpMenu(comp, 80@20)
        .items_(Array.fill(16, { arg i; (i+1).asString }))
        .value_(startChan)
        .action_({ arg menu; chan = menu.value; });

    // Fader factory tied to this specific box
    ~makeFader = { arg labelName, ccNum, initVal;
        EZSlider(comp, 300@25, labelName, ControlSpec(0, 127, \lin, 1, 0), { arg sl;
            ~midiOut.control(chan, ccNum, sl.value.asInteger);
        }, initVal, labelWidth: 60).doAction;
    };

    // LFO Faders (Freq & Amp only)
    ~makeFader.value("LFO Freq", 76, 64);
    ~makeFader.value("LFO Amp", 77, 64);
};

// 4. Generate the UI Elements
// Generate 4 ADSR Sets
StaticText(~container, 660@25).string_("ADSR ENVELOPES").align_(\center).font_(Font("Helvetica", 16, true));
~container.decorator.nextLine;
4.do { arg i; ~createVoiceSet.value("VOICE " ++ (i + 1), i); };

// Visual Break
~container.decorator.nextLine;
~container.decorator.shift(0, 10);

// Generate 4 LFO Sets
StaticText(~container, 660@25).string_("LFOs").align_(\center).font_(Font("Helvetica", 16, true));
~container.decorator.nextLine;
4.do { arg i; ~createLFOSet.value("LFO " ++ (i + 1), i); };

~win.front;
~win.onClose = { "Befaco Controller Closed.".postln; };

// 5. SuperDirt Setup
s.waitForBoot {
	~dirt = SuperDirt();
    ~dirt.loadSoundFiles();
    s.sync;
    ~dirt.start;
    s.sync;
    ~dirt.soundLibrary.addMIDI(\befaco, ~midiOut);
    "SuperDirt ready!".postln;
};
)

