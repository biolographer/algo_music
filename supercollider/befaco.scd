// 1. Manually boot ONE synth
~testLFO = Synth(\befacoLFO, [\freq, 2, \midichan, 0]);

// 2. Sequence its parameters using \type, \set
(
~lfoModulator = Pbind(
    \type, \set,            // Tell SC not to spawn new synths
    \id, ~testLFO.nodeID,   // Point directly to your active LFO
    \args, #[\freq],        // Tell it which parameters to touch
    \dur, 0.5,
    \freq, Pseq([2, 8, 0.2, 4], inf)
).play;
)

// 3. Cleanup
~lfoModulator.stop;
~testLFO.free;



(
// Re-evaluate this block as much as you want.
// SuperCollider will change the frequency smoothly without layering.
Pdef(\cvChannel0,
    Pmono(\befacoLFO,
        \midichan, 0,
        \freq, 1,       // Change this and hit evaluate!
        \polarity, 1,   // Change unipolar/bipolar
        \dur, 1.0       // standard SC requirement to keep the sequence open
    )
).play;
)

// Stops the sequencer and automatically frees the LFO node.
Pdef(\cvChannel0).stop;