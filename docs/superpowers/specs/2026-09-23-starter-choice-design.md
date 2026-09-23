# Jev picks the starter

Issue #80. Amends `2026-09-20-jevplays-design.md` (the starter confirmation paragraph).

## The decision

Until now the starter was code's choice. `get_starter` walked to Charmander's ball and ran
`choose_charmander`. The design doc scripted the confirmation YES because "Jev already decided to
come and take the ball", but nothing ever asked Jev which ball. The choice is a real judgment
with consequences Jev can weigh, and it is the most recognisable decision in the game for anyone
watching the demo, so it is Jev's.

## What Jev is asked

One `choice` question, `starter`, asked once, when the `get_starter` milestone reaches Oak's
table:

- **instructions:** "Which starter POKéMON should we take from Professor Oak? It will be our only
  POKéMON at first, and it has to carry us to "goal"."
- **criteria:** each starter by type, in the game's own words for it:
  - BULBASAUR: "Grass-type, the plant POKéMON"
  - CHARMANDER: "Fire-type, the fire POKéMON"
  - SQUIRTLE: "Water-type, the water POKéMON"
- **state:** `{"goal": <the last milestone's description>}`, "Challenge Brock at the Pewter Gym
  and earn the Boulder Badge". That is the same wording Jev already sees as a milestone.

Jev is never told which type beats which. That stays in `state/types.py`, for measurement only.
Whether Jev knows Brock fields Rock types is its own judgment.

## What code does

- `brain/starter.py` asks the question and decodes the answer into a `StarterAction`.
- An answer that is not one of the three falls back to CHARMANDER and is marked as a fallback.
- A run without a brain takes CHARMANDER, as before, so offline runs are unchanged.
- In the lab, the milestone's leg walks to the table. The `choose_starter` macro then asks the
  question and `Loop._take_starter` walks to the chosen ball's tile (`goals.STARTER_TILES`,
  checked against the ROM), faces up, and presses A. The confirmation stays a scripted YES and the
  nickname a scripted NO.
- If TypeSafe is unavailable, nothing is taken and the table asks again next turn.

## The demo

`Scripts/demo-loop.py` starts every run from the intro by default. The intro itself is code
pressing through dialog. The first decision a viewer sees is the starter. `--state` still
starts runs from a save.

## Knock-on effects

- The rival takes the starter that counters Jev's, so the lab battle changes.
- Brock is easier with SQUIRTLE or BULBASAUR.
- Tests built on `states/route1.state` keep their CHARMANDER.
- Fixture: `starter_choice`, recorded at Oak's table.
