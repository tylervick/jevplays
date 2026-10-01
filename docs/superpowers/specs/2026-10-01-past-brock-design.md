# Past Brock: Misty and the Cascade Badge, opt-in

Amends `2026-09-21-generated-options-design.md` (milestones) and `2026-09-22-map-graph-design.md`
(routing). The base rules hold: Jev judges, code executes; the milestones in `executor/goals.py`
are the only hand-written story; never hand-write map waypoints.

## Why now

#35 showed exploration alone carries a run from Pewter through Route 3 and Mt. Moon to Route 4,
one map from Cerulean, and the graph the run builds as it walks gives it a way back to heal and
shop. #110 (direction B) made Jev build a party; a party, training, and Poké Balls bought late are
all worth more with ground past Pewter to use them on.

## What changes

1. **A fourth milestone, `beat_misty`**: "Challenge Misty at the Cerulean Gym and earn the Cascade
   Badge". Available once the Boulder Badge is held, done when the badge count reaches two,
   `expects_level` 21 (Misty's Starmie). Its legs route to the `cerulean_gym` node over the run's
   walked graph, then hand over to a `talk_leader` macro.
2. **No route, no milestone option.** A milestone may name a `destination` node. When it does, the
   run is not standing there, and the route comes back empty, the milestone is not offered: the
   run has not walked there yet, and the exits and doors carry it (#53's lesson: a beat Jev can
   reach by exploring is not a goal). Milestones without a destination behave as before.
3. **Map facts.** `NODE_NAMES`/`MAP_IDS` gain `cerulean_city` (3), `cerulean_pokecenter` (64),
   `cerulean_gym` (65), `cerulean_mart` (67); the place names table gains Mt. Moon B1F/B2F, the
   Cerulean buildings and the Mt. Moon Pokémon Center (60–68). `ram.MART_INVENTORIES` gains the
   Cerulean Mart at `0x2453` (POKE BALL, POTION, REPEL, ANTIDOTE, BURN HEAL, AWAKENING, PARLYZ HEAL),
   the third entry of the ROM's Mart inventory table. No links are hand-written past Pewter.
4. **`talk_leader`.** In a gym the leader is the northernmost person on the map; the macro walks to
   the tile in front of them and talks. Brock keeps his verified tile.
5. **Opt-in.** `LoopConfig.until` (`--until`, default `beat_brock`) names the last milestone a run
   works towards; `active_milestone(state, until=...)` stops there. The default keeps every existing
   run, test, measurement series and the demo ending at the Boulder Badge; `--until beat_misty` goes
   on. Each milestone that ends in a badge names it (`Goal.badge`), and the finish message names the
   final milestone's badge.

## Measuring it

Unpaced runs from `states/brock_award.state` with `--until beat_misty`: how far each gets (maps
reached, Cerulean entered, badge two), decisions spent, blackouts, and where any stall or loop
clusters. Expect the first runs to find new executor gaps, as every past measurement has; those are
fixed as they are found.
