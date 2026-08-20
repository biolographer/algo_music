:set -fno-warn-orphans -Wno-type-defaults -XMultiParamTypeClasses -XOverloadedStrings
:set prompt ""

-- Import all the boot functions and aliases.
import Sound.Tidal.Boot

default (Rational, Integer, Double, Pattern String)

-- Create a Tidal Stream with the default settings.
-- To customize these settings, use 'mkTidalWith' instead



-- %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
-- %%%%%%% TIME SIGNATURES %%%%%%%%
-- %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%


-- for 4/4 beats
-- tidalInst <- mkTidal

-- for 5/4 beats
tidalInst <- mkTidalWith [(superdirtTarget { oLatency = 0.01 }, [superdirtShape])] (defaultConfig {cFrameTimespan = 1/50, cProcessAhead = 1/20, cQuantum = 5, cBeatsPerCycle = 5})

-- tidalInst <- mkTidalWith [(superdirtTarget { oLatency = 0.01 }, [superdirtShape])] (defaultConfig {cFrameTimespan = 1/50, cProcessAhead = 1/20})

-- %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%




-- This orphan instance makes the boot aliases work!
-- It has to go after you define 'tidalInst'.
instance Tidally where tidal = tidalInst

-- `enableLink` and `disableLink` can be used to toggle synchronisation using the Link protocol.
-- Uncomment the next line to enable Link on startup.
enableLink

-- You can also add your own aliases in this file. For example:
-- fastsquizzed pat = fast 2 $ pat # squiz 1.5

:set prompt "tidal> "
:set prompt-cont ""


-- %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
-- %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
-- CUSTOM FUNCTIONS
-- %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%
-- %%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%%


-- Tintinnabuli pattern generator
-- example:
-- d1 $ slow 2 $ stack  [ n (tintin "4" "a'min" "c3 e3 d3 f3") # s "befaco"

let tintin :: Pattern Double -> Pattern Note -> Pattern Note -> Pattern Note
    tintin offP chordP melP =
      (((\mel off tones -> pick tones (unNote mel + off)) <$> melP)
         `applyPatToPatLeft` offP)
         `applyPatToPatLeft` collect chordP
      where
        pick tones target
          | null cands = Note target
          | otherwise  = snd $ minimum [ (abs (c - target), Note c) | c <- cands ]
          where
            cands = [ unNote t + 12 * o | t <- tones, o <- [-5 .. 5] ]


-- Rhythmic humanization
-- 
-- example:
-- 
--   d1 $ cycleDrift 4 0.02      -- Every 4th cycle, this track "pushes" ahead
--   $ s "bd [~ sn] bd*2 [~ sn]"
--   # drift 0.05 
--

let
  staticDrift = (slow 32 $ range (-0.02) 0.02 sine) + (slow 8 $ range (-0.01) 0.01 rand)

-- Define a global "Group Tension"
let 
    drift val = nudge $ (range 0 1 $ slow 16 $ tri) * val -- val ~0.05
    cycleDrift c val = chunk c (|+ nudge val) -- c = cycle length, val ~0.02

let 
    drift' = drift 0.05
    cycleDrift' = cycleDrift 4 0.02

