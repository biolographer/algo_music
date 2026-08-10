s.boot;

(
OSCdef(\midiBendSender, { |msg|
    var val = msg[3];
    var channel = msg[4].asInteger;
    var pbVal = val.linlin(-1.0, 1.0, 0, 16383).clip(0, 16383).asInteger;
    ~befacoOut.bend(channel, pbVal);
}, '/sendBend');

// =========================================================
// A. CV ENVELOPES (Persistent / Monophonic)
// Controlled via `gate` or `t_trig`. Do not re-trigger to 0.
// =========================================================

// ADSR Envelope: Send gate=1 to attack/sustain, gate=0 to release
SynthDef(\befacoADSR, { |gate=0, attack=0.1, decay=0.2, susLevel=0.5, release=0.3, att=1, polarity=0, midichan=0|
    var base = EnvGen.kr(Env.adsr(attack, decay, susLevel, release), gate);
    var sig = (base * (1 + polarity) - polarity) * att;
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
}).add;

// AD (Attack-Decay) Envelope: Fire using t_trig=1
SynthDef(\befacoAD, { |t_trig=0, attack=0.01, decay=0.5, att=1, polarity=0, midichan=0|
    // Creates a gate that matches the exact length of the attack phase
    var internalGate = Trig.kr(t_trig, attack);
    // Uses ADSR logic but sustain is 0, so it naturally decays in the release phase.
    var base = EnvGen.kr(Env.adsr(attack, 0, 0, decay), internalGate);
    var sig = (base * (1 + polarity) - polarity) * att;
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
}).add;

// =========================================================
// B. CONTINUOUS CV GENERATORS
// =========================================================

SynthDef(\befacoLFO, { |freq=1, att=1, polarity=0, midichan=0|
    var smoothFreq = VarLag.kr(freq, 0.1, warp: \lin);
    var smoothAtt = VarLag.kr(att, 0.1, warp: \lin);
    var base = SinOsc.kr(smoothFreq);
    var sig = ((base * (1 + polarity) + (1 - polarity)) / 2) * smoothAtt;

    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    //Out.ar(0, Silent.ar(1)); // Force server to process node!
}).add;


SynthDef(\befacoPitch, { |midinote=60, portamento=0, midichan=0|
    var smoothNote = VarLag.kr(midinote, portamento, warp: \lin);
    var sig = (smoothNote - 60) / 60;
    sig = sig.clip(-1.0, 1.0);
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
}).add;

// =========================================================
// C. GATES & TRIGGERS (Event Based)
// Replaced Env.step with Line.kr for stable doneAction timing
// =========================================================

// Tied to sustain: holds Gate high until the Pbind dur/sustain is over
SynthDef(\befacoEventGate, { |sustain=1, note=60, vel=127, midichan=0|
    // Line counts from $0$ to $1$ over 'sustain' seconds, then frees the synth
    var timer = Line.kr(0, 1, sustain, doneAction: 2);

    // Impulse fires exactly once at node creation
    SendReply.kr(Impulse.kr(0), '/sendGateOn', [note, vel, midichan]);

    // Done.kr changes from $0$ to $1$ exactly when 'timer' finishes
    SendReply.kr(Done.kr(timer), '/sendGateOff', [note, midichan]);
}).add;

// Instant Trigger spike ($0.01$ seconds)
SynthDef(\befacoEventTrig, { |note=60, vel=127, midichan=0|
    var timer = Line.kr(0, 1, 0.01, doneAction: 2);

    SendReply.kr(Impulse.kr(0), '/sendGateOn', [note, vel, midichan]);
    SendReply.kr(Done.kr(timer), '/sendGateOff', [note, midichan]);
}).add;



// 1. Connect the MIDI Out

MIDIClient.init;
~befacoOut = MIDIOut.newByName("MIDIThing2", "MIDIThing2");
~befacoOut.latency = 0;


// 2. Start the OSC Listeners (These catch the SendReply.kr messages from the Synths)
OSCdef(\midiBendSender, { |msg|
    var val = msg[3]; // The CV value (-1.0 to 1.0)
    var channel = msg[4].asInteger; // MIDI Channel
    var pbVal = val.linlin(-1.0, 1.0, 0, 16383).clip(0, 16383).asInteger;
    ~befacoOut.bend(channel, pbVal);
}, '/sendBend');

OSCdef(\midiGateOnSender, { |msg|
    var note = msg[3].asInteger;
    var vel = msg[4].asInteger;
    var channel = msg[5].asInteger;
    ~befacoOut.noteOn(channel, note, vel);
}, '/sendGateOn');

OSCdef(\midiGateOffSender, { |msg|
    var note = msg[3].asInteger;
    var channel = msg[4].asInteger;
    ~befacoOut.noteOff(channel, note, 0);
}, '/sendGateOff');

"Befaco MIDI link established!".postln;
)




