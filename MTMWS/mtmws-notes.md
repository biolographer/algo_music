# Card ideas

## Jux Midi
- Record midi notes in a buffer
- Play the notes through two output channels
- Choose number of notes to be replayed by two channels with X and Y
    - between 2-12 notes
    - 6 LED's can indicate the number (in binary for fun or just 2-6 and then another 2-6 when pot is moved past 12 o'clock)
- Big knob controls time shift between midi notes
    - [ ] Make it go such note 1 can maximally be shifted to note N of a pattern length N
- Switch
    - Up: live mode, MIDI notes pass through
    - Middle: grab the notes from the buffer, repeat in a loop of lengths set by knob X and Y
    - Down toggle: Reverse the order of the notes in the Channel2 buffer

## Jux audio
- Record incoming audio stream
- Striate it
    - Transient detection?
    - Split evenly?
- Reversable
- Time shift
- Inspiration: 
    - 11_goldfish card
    - Utility_pair (https://github.com/chrisgjohnson/Utility-Pair/)