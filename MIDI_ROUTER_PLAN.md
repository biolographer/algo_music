# MIDI Synth 12-Channel Router - Implementation Plan

## Project Overview
A modular PureData system to route MIDI input from a DAW to 12 independent output channels, each with selectable source:
1. **Pitch** - MIDI note with 1V/octave CV scaling
2. **Velocity** - MIDI velocity passthrough
3. **Gate** - Note on/off binary gate
4. **Trigger** - Pulse on note event
5. **ADSR Envelope** - ELLE adsr~ with per-channel parameters
6. **AR Envelope** - ELSE asr~ with per-channel parameters
7. **LFO** - Free-running from befaco_lfo.pd
8. **Clock Division** - Integer divisions (1/1 to 1/64) of MIDI clock

## Voltage/Range Specifications
- **1V/octave scaling**: Middle C (note 60) = 0V
- **Full range**: -5V to +5V (represented as pitchbend -8192 to +8191)
- **Formula**: `V = ((note - 60) / 12) + ((pitchbend / 8191.5) × 5)`
- **Non-pitch sources** (0-127): map through range-mapper.pd to pitchbend range

## Files Created So Far

### Core Utilities
- ✅ `range-mapper.pd` - Maps 0-127 to pitchbend (-8192 to +8191)

### MIDI Sources
- ✅ `midi-velocity.pd` - Passthrough velocity (0-127)
- ✅ `midi-gate.pd` - Gate output (0 or 127)
- ✅ `midi-trigger.pd` - Trigger pulse (127 → 0 over 50ms)
- ✅ `midi-adsr.pd` - ELSE adsr~ envelope with UI sliders (A, D, S, R in ms)
- ✅ `midi-ar.pd` - ELSE asr~ envelope with UI sliders (A, R in ms)
- ✅ `clock-divider.pd` - MIDI clock divider (1 to 64)
- ✅ `pitch-source.pd` - 1V/octave pitch with scl_reader integration
- ✅ `lfo-module.pd` - Wrapper/placeholder for befaco_lfo.pd

### Integration (In Progress)
- ⚠️ `channel-router.pd` - NEEDS COMPLETION: Single-channel router with source selection, MIDI ch filter, output mapping
- ⚠️ `midi-synth-12ch.pd` - NEEDS COMPLETION: Master patcher coordinating 12 instances

## Detailed Architecture

### Signal Flow (Per Channel)
```
MIDI Input (notein)
    ├─ Note number → [pitch-source] or other sources
    ├─ Velocity → [midi-velocity]
    └─ Gate (note on/off) → [midi-gate] or [adsr]/[ar] trigger

MIDI Channel Filter
    └─ Compare incoming MIDI ch with per-channel filter setting

Source Selector
    ├─ 1: Pitch source → range-mapper → pitchbend
    ├─ 2: Velocity → range-mapper → pitchbend
    ├─ 3: Gate → range-mapper → pitchbend
    ├─ 4: Trigger → range-mapper → pitchbend
    ├─ 5: ADSR → range-mapper → pitchbend
    ├─ 6: AR → range-mapper → pitchbend
    ├─ 7: LFO (direct, already in pitchbend range)
    └─ 8: Clock Divider → range-mapper → pitchbend

Output
    └─ bendout on channel 1-12
```

## MIDI Channel Filtering
- Each output channel has a filter parameter (1-16 or "all")
- Only processes MIDI input if incoming channel matches filter
- Allows mapping different DAW tracks to different hardware outputs

## Per-Channel Parameters

### For ADSR Source:
- Attack (10-2000 ms)
- Decay (10-2000 ms)
- Sustain (0-1.0)
- Release (10-2000 ms)

### For AR Source:
- Attack (10-2000 ms)
- Release (10-2000 ms)

### For Clock Division Source:
- Division ratio (1-64)

### For LFO Source:
- Waveform (sine, saw, tri, square) - from befaco_lfo
- Frequency (Hz) - from befaco_lfo
- Morph/blend - from befaco_lfo

### For Pitch Source:
- EDO or custom tuning file (via scl_reader)

## Next Steps

1. **Complete channel-router.pd**
   - Full routing logic: MIDI ch filter → source selection → output mapping
   - Gate/velocity extraction from notein
   - Per-channel parameter send/receive for ADSR/AR

2. **Complete midi-synth-12ch.pd**
   - Instantiate 12× channel-router
   - Route MIDI clock input
   - Create per-channel UI sections for parameter editing
   - Test MIDI input reception

3. **Testing Strategy**
   - Test each source in isolation within a single channel
   - Test multiple channels simultaneously
   - Test MIDI channel filtering
   - Verify 1V/octave scaling with pitch source
   - Verify envelope retriggering on each new note

## Existing Resources to Integrate
- `befaco_lfo.pd` - Morph LFO with sine/saw/tri/square + noise blend
- `befaco_pitch.pd` - Pitch quantizer with EDO/Scala tuning support
- `scl_reader` external - Scala format tuning file loader
- `scl_reader_test.pd` - Example usage

## File Locations
All abstractions: `/Users/aaron/Documents/Code/algo_music/pd-abstractions/`
