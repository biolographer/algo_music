(
// =========================================================
// 1. LEXICAL MEMORY (CRITICAL FIX)
// These variables exist outside Tidal's Event Environment,
// so they can never accidentally become 'nil'.
// =========================================================
var globalCVs = Dictionary.new;
var memBusses;

// =========================================================
// 2. SERVER & MIDI CONFIGURATION
// =========================================================

// s.options.outDevice = "External Headphones"; // Uncomment if strictly needed
s.options.numOutputBusChannels = 2;

MIDIClient.init;
~befacoOut = MIDIOut.newByName("MIDIThing2", "MIDIThing2");
~befacoOut.latency = 0;

// =========================================================
// 3. OSC LISTENER & SYNTHDEFS
// =========================================================

OSCdef(\midiBendSender, { |msg|
    var val = msg[3];
    var channel = msg[4].asInteger;
    var pbVal = val.linlin(-1.0, 1.0, 0, 16383).clip(0, 16383).asInteger;
    ~befacoOut.bend(channel, pbVal);
}, '/sendBend');


// === A. 808 CV ENVELOPES ===
SynthDef(\kick808, { |out=0, decay=0.8, amp=1, att=1, polarity=0, midichan=0, memBus=0|
    var startVolt = Latch.kr(In.kr(memBus), Impulse.kr(0));
    var env = Env([startVolt, 1, 0.001], [0.001, decay], \exp);
    var base = EnvGen.kr(env, doneAction: 2);
    var sig = (base * (1 + polarity) - polarity) * att * amp;

    ReplaceOut.kr(memBus, base);
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;

SynthDef(\snare808, { |out=0, amp=1, snappy=0.5, decay=0.2, att=1, polarity=0, midichan=0, memBus=0|
    var startVolt = Latch.kr(In.kr(memBus), Impulse.kr(0));
    var toneEnv = EnvGen.kr(Env([startVolt, 1, 0], [0.001, 0.1], -4));
    var noiseEnv = EnvGen.kr(Env([startVolt, 1, 0], [0.001, decay], -4), doneAction: 2);
    var base = (toneEnv + (noiseEnv * snappy)).clip(0, 1);
    var sig = (base * (1 + polarity) - polarity) * att * amp;

    ReplaceOut.kr(memBus, base);
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;

SynthDef(\hat808, { |out=0, amp=1, decay=0.1, att=1, polarity=0, midichan=0, memBus=0|
    var startVolt = Latch.kr(In.kr(memBus), Impulse.kr(0));
    var env = Env([startVolt, 1, 0], [0.005, decay], -4);
    var base = EnvGen.kr(env, doneAction: 2);
    var sig = (base * (1 + polarity) - polarity) * att * amp;

    ReplaceOut.kr(memBus, base);
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;

SynthDef(\clave808, { |out=0, amp=1, decay=0.05, att=1, polarity=0, midichan=0, memBus=0|
    var startVolt = Latch.kr(In.kr(memBus), Impulse.kr(0));
    var env = Env([startVolt, 1, 0], [0.001, decay], -4);
    var base = EnvGen.kr(env, doneAction: 2);
    var sig = (base * (1 + polarity) - polarity) * att * amp;

    ReplaceOut.kr(memBus, base);
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;


// === B. STANDARD TRANSIENT CV ===
SynthDef(\midiADSR, { |out=0, sustain=1, attack=0.1, decay=0.2, susLevel=0.5, release=0.3, att=1, polarity=0, midichan=0, memBus=0|
    var gate = Trig.kr(1, max(0.01, sustain - release));
    var startVolt = Latch.kr(In.kr(memBus), Impulse.kr(0));
    var env = Env([startVolt, 1, susLevel, 0], [attack, decay, release]);
    var base = EnvGen.kr(env, gate, doneAction: 2);
    var sig = (base * (1 + polarity) - polarity) * att;

    ReplaceOut.kr(memBus, base);
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;

SynthDef(\midiAR, { |out=0, sustain=1, attack=0.1, release=0.9, att=1, polarity=0, midichan=0, memBus=0|
    var startVolt = Latch.kr(In.kr(memBus), Impulse.kr(0));
    var env = Env([startVolt, 1, 0], [attack, release], -4);
    var base = EnvGen.kr(env, doneAction: 2);
    var sig = (base * (1 + polarity) - polarity) * att;

    ReplaceOut.kr(memBus, base);
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;

SynthDef(\midiOffset, { |out=0, sustain=1, offset=0.5, att=1, polarity=0, midichan=0, memBus=0|
    var base = DC.kr(offset);
    var alive = EnvGen.kr(Env([1, 1], [sustain]), doneAction: 2);
    var sig = (base * (1 + polarity) - polarity) * att;

    ReplaceOut.kr(memBus, base);
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;

SynthDef(\midiNoise, { |out=0, sustain=1, lfoRate=10, att=1, polarity=0, midichan=0, memBus=0|
    var base = LFNoise0.kr(lfoRate);
    var alive = EnvGen.kr(Env([1, 1], [sustain]), doneAction: 2);
    var sig = ((base * (1 + polarity) + (1 - polarity)) / 2) * att;

    ReplaceOut.kr(memBus, ((base + 1) / 2));
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;

SynthDef(\midiSmoothNoise, { |out=0, sustain=1, lfoRate=2, att=1, polarity=0, midichan=0, memBus=0|
    var base = LFNoise2.kr(lfoRate);
    var alive = EnvGen.kr(Env([1, 1], [sustain]), doneAction: 2);
    var sig = ((base * (1 + polarity) + (1 - polarity)) / 2) * att;

    ReplaceOut.kr(memBus, ((base + 1) / 2));
    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;


// === C. FREE-RUNNING CONTINUOUS CV ===
SynthDef(\midiLFO_Continuous, { |out=0, freq=1, att=1, polarity=0, midichan=0|
    var smoothFreq = VarLag.kr(freq, 0.1, warp: \lin);
    var smoothAtt = VarLag.kr(att, 0.1, warp: \lin);
    var base = SinOsc.kr(smoothFreq);
    var sig = ((base * (1 + polarity) + (1 - polarity)) / 2) * smoothAtt;

    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;

SynthDef(\midiSmooth_Continuous, { |out=0, lfoRate=2, att=1, polarity=0, midichan=0|
    var smoothRate = VarLag.kr(lfoRate, 0.1, warp: \lin);
    var smoothAtt = VarLag.kr(att, 0.1, warp: \lin);
    var base = LFNoise2.kr(smoothRate);
    var sig = ((base * (1 + polarity) + (1 - polarity)) / 2) * smoothAtt;

    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;

SynthDef(\midiPitch_Continuous, { |out=0, midinote=60, portamento=0, midichan=0|
    var smoothNote = VarLag.kr(midinote, portamento, warp: \lin);
    var sig = (smoothNote - 60) / 60;
    sig = sig.clip(-1.0, 1.0);

    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;

SynthDef(\midiVolts_Continuous, { |out=0, volts=0, portamento=0, midichan=0|
    var smoothVolts = VarLag.kr(volts, portamento, warp: \lin);
    var sig = smoothVolts / 5.0;
    sig = sig.clip(-1.0, 1.0);

    SendReply.kr(Impulse.kr(100), '/sendBend', [sig, midichan]);
    Out.ar(out, Silent.ar(2));
}).add;


// =========================================================
// 4. SERVER BOOT & SUPERDIRT INITIALIZATION
// =========================================================

s.waitForBoot {

    // Safely assign memory busses once server is booted
    memBusses = Array.fill(16, { Bus.control(s, 1).set(0) });

    // Open 16 Orbits so d1 through d16 all work perfectly without warnings
    ~dirt = SuperDirt(16, s);
    ~dirt.loadSoundFiles;
    s.sync;

    // ---------------------------------------------------------
    // 5. SILENCE WARNINGS & ADD MODULES
    // ---------------------------------------------------------

    // Tell SuperDirt these are valid names so it doesn't look for .WAV files and complain
    [\setLFO, \setSmooth, \setPitchCV, \setRawVolts, \midiADSR, \midiAR, \midiOffset, \midiNoise, \midiSmoothNoise, \kick808, \snare808, \hat808, \clave808].do { |name|
        ~dirt.soundLibrary.addSynth(name, (play: {}));
    };

    // CONTINUOUS CV ROUTER
    ~dirt.addModule('setContinuousCV', { |dirtEvent|
        var chan = (~midichan ? 0).asInteger;
        var reqType = ~s.asSymbol;
        var currentData = globalCVs[chan];

        var createNewSynth = {
            var newSynth = switch(reqType,
                'setLFO', { Synth(\midiLFO_Continuous, [\freq, ~freq ? 1, \att, ~att ? 1, \polarity, ~polarity ? 0, \midichan, chan]) },
                'setSmooth', { Synth(\midiSmooth_Continuous, [\lfoRate, ~lfoRate ? 2, \att, ~att ? 1, \polarity, ~polarity ? 0, \midichan, chan]) },
                'setPitchCV', { Synth(\midiPitch_Continuous, [\midinote, ~midinote ? 60, \portamento, ~porta ? 0, \midichan, chan]) },
                'setRawVolts', { Synth(\midiVolts_Continuous, [\volts, ~volts ? 0, \portamento, ~porta ? 0, \midichan, chan]) }
            );
            // Register synth so SC tracks if it's dead or alive
            NodeWatcher.register(newSynth);
            globalCVs[chan] = (synth: newSynth, type: reqType);
        };

        if(currentData.isNil) {
            createNewSynth.value();
        } {
            // Is it a different synth? Hunt it down safely!
            if(currentData[\type] != reqType) {
                if(currentData[\synth].isPlaying) { currentData[\synth].free; };
                createNewSynth.value();
            } {
                // Same synth! Just safely update parameters
                if(currentData[\synth].isPlaying) {
                    switch(reqType,
                        'setLFO', { currentData[\synth].set(\freq, ~freq ? 1, \att, ~att ? 1, \polarity, ~polarity ? 0) },
                        'setSmooth', { currentData[\synth].set(\lfoRate, ~lfoRate ? 2, \att, ~att ? 1, \polarity, ~polarity ? 0) },
                        'setPitchCV', { currentData[\synth].set(\midinote, ~midinote ? 60, \portamento, ~porta ? 0) },
                        'setRawVolts', { currentData[\synth].set(\volts, ~volts ? 0, \portamento, ~porta ? 0) }
                    );
                } {
                    // Edge case: It's the same type, but it died somehow. Respawn it.
                    createNewSynth.value();
                };
            };
        };
    }, { [\setLFO, \setSmooth, \setPitchCV, \setRawVolts].includes(~s.asSymbol) });


    // ALL-SEEING TRANSIENT CV ROUTER
    ~dirt.addModule('midiTransients', { |dirtEvent|
        var chan = (~midichan ? 0).asInteger;
        var reqType = ~s.asSymbol;
        var currentData = globalCVs[chan];

        // AUTO-CHOKE: Only free the old synth IF it is actually still alive playing
        if(currentData.notNil and: { currentData[\synth].isPlaying }) {
            currentData[\synth].free;
        };

        // NATIVE SPAWN
        ~transientObj = Synth(reqType, [
            \attack, ~attack ? 0.1,
            \decay, ~decay ? 0.2,
            \release, ~release ? 0.3,
            \sustain, ~sustain ? 1,
            \susLevel, ~susLevel ? 0.5,
            \offset, ~offset ? 0.5,
            \lfoRate, ~lfoRate ? 2,
            \amp, ~amp ? 1,
            \snappy, ~snappy ? 0.5,
            \midichan, chan,
            \polarity, ~polarity ? 0,
            \att, ~att ? 1,
            \memBus, memBusses[chan]
        ]);

        // Register the new transient so SC knows when it dies naturally
        NodeWatcher.register(~transientObj);

        globalCVs[chan] = (
            type: reqType,
            synth: ~transientObj
        );

    }, { [\midiADSR, \midiAR, \midiOffset, \midiNoise, \midiSmoothNoise, \kick808, \snare808, \hat808, \clave808].includes(~s.asSymbol) });

    // Start Audio
    ~dirt.start;

    "\n*** SuperDirt + Befaco CV Router is completely optimized & ready. ***\n".postln;
};
)