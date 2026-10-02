# Places are pockets: routing and the frontier inside a cave (#137)

Amends `2026-09-22-map-graph-design.md` (the walked graph) and `2026-09-21-generated-options-design.md`
sections 2 and 3 (options and memory words). The base rules hold: Jev judges, code executes; no
coordinates or raw numbers reach Jev; never hand-write the way to a milestone; it is routed over the
graph the run walks.

## 1. The problem, with numbers

The walked graph names a place by map id (Route 2's two halves are the one hand-coded exception).
A cave floor is several walled-off pockets under one id. Everything keyed by place is therefore
wrong inside Mt. Moon, and the past-Brock probe rounds show each way it is wrong:

- **A route that cannot start here.** Round 11, fresh run: Charmeleon at critical HP in Mt. Moon
  1F chose `go heal at Pewter Pokémon Center (tried)` 4,731 times at 0.65. The trip was offered from
  a 1F pocket that cannot walk to the entrance; its first leg failed on the spot, every 0.17 s. #133
  stopped doors and heal trips whose first warp the grid can judge unreachable; the entrance mat
  sits on a tile the grid cannot judge, so it was let through.
- **No frontier word inside the cave.** Round 11, resumed run: after #142 every ladder in 1F read
  `(tried)` (each had led straight back up from a B1F pocket) and so did `go back outside`; the run
  bounced 1F ↔ Route 4 about 2,500 times. The way on, B2F's unvisited ladders, is in no word Jev
  sees. Rounds 9 and 10 were the same loop before the marks existed. "Leads nowhere new" is trusted
  only for buildings (`Memory.buildings`), because a search over map ids claimed it for a floor
  whose other ladders lead on.
- **The town map has one cell for the whole cave,** so the direction word (#139) is silent from 1F
  down, by construction. Route 4 is two pockets with one cell, which #139 papers over with its
  "unreachable connection" rule.

Rounds 6 to 11 reached B2F in nearly every run and B1F's exit pocket once. Nothing past that.

## 2. A place is (map, pocket)

A **pocket** is a connected component of the map's walkable grid under `MapGrid.can_step` (tile
pairs honoured, #126), computed from the grid the run already builds every turn. Sprites do not
split pockets: they move. Pocket ids are the rank of each component's smallest `(y, x)` cell, so
they are stable across visits and across runs.

A **place name** is what `maps.node_of` returns today for a map in `NODE_NAMES` (one place per
named map: towns, routes before Pewter, buildings, the Cerulean nodes) and for Route 2 (its row
split stays: the curated layer is not touched). For every other map, `map_<id>` becomes
`map_<id>_p<k>` when the map has more than one pocket and stays `map_<id>` when it has one.

Naming a pocket needs the grid, and `legs_to` and the milestones' legs functions only have the
state. So the place is a fact on the state: **`GameState.place`**, computed by `snapshot` from
`maps.node_of` for a named map and from `world.pocket_of(grid, x, y)` otherwise, building the grid
only for a map outside `NODE_NAMES`. `goals.node(state)` returns it; the loop's crossing bookkeeping
names both ends from the snapshots it already takes. `node_of(map_id, x, y)` keeps its signature
and its answers for named maps and Route 2; `map_id_of` learns the `_p<k>` suffix.

**Why not every map.** Towns have one-way ledges that the symmetric `can_step` would turn into
pockets, and nothing past Pewter needs them split. Keeping named maps as one place keeps `LINKS`,
the Route 2 split, `CENTERS` and every existing test exactly as they are. If a named map ever
shows the #133 symptom, that map joins the pocketed set by being dropped from `NODE_NAMES`, not by
another rule.

## 3. What is keyed by place

- **`Memory.links`** already keys by node name, so crossings between pockets are recorded for free
  once `node_of` names pockets. The way back out of a cave pocket is the warp the run took, as now.
- **`Memory.exits`** (what was offered where) becomes `exits: dict[str, set[Landing]]` keyed by
  place, with a `Landing` being `("edge", dest_map, direction)` or `("warp", dest_map, warp_id)`:
  the identity of a way out as the option generator sees it, before it is known where it lands.
- **`Memory.landings: dict[Landing, str]`** records the place each landing was found to lead to,
  written at the same moment as the crossing. `Memory.ladders` is subsumed: a ladder is "visited"
  when its landing has a recorded place.
- **`Memory.buildings`** goes. A building is an indoor map with one pocket, which the search in
  section 4 handles without a special case.

`memory.json` written before this change loads: `exits` in the old shape (map id → map ids) is
dropped on read rather than converted, `landings` starts empty, and `ladders` is read into
`landings` with the place unknown (`None`: taken, so still "visited", but the search cannot follow
it). A resumed run from before the change re-learns the cave; it loses nothing before Pewter
because those names do not change.

## 4. The frontier word, generalised

`Memory.dead_end(here, dest)` is replaced by `leads_nowhere_new(here_place, landing)`:

> Follow the landing to its place. A landing with no recorded place, or one on an outdoor map
> (id below `FIRST_INDOOR_MAP`), is never said to lead nowhere new: the first is untaken, the
> second opens onto the world. Otherwise search outward over recorded landings, never back
> through `here_place` and never into an outdoor map. The door leads nowhere new when every
> place reached has every offered landing recorded, i.e. nothing reachable beyond the door has
> an untaken way out.

A building is the one-place case: its only landing is the door back, recorded, so it leads nowhere
new, exactly as today. A B1F pocket whose ladder down reaches a B2F pocket with an untaken ladder
does not. A B1F pocket whose whole subtree is taken does. Route 4's west end seen from 1F is an
outdoor map, so the search stops at it and says nothing: the earlier objection to a search over
map ids (it said "nowhere new" wrongly) was about pockets, which this search has, and the earlier
objection to "leads on to new places" (it pulled Jev toward Pewter's unvisited houses) is about
the positive word, which is still never said.

The memory word stays `visited, leads nowhere new`, and the explore question's gloss changes from
"a building whose only way out is back here" to "a place beyond which everything has already been
seen". That is a wording change: the explore fixture re-records.

## 5. Routing over places

`maps.route`, `legs_to`, `_heal_option` and `_milestone_option` are unchanged in shape; they now
run over pocket names because the links do. Two consequences:

- A heal trip from a 1F pocket is planned over links recorded *from that pocket*, so its first leg
  is a warp or edge this pocket has actually used. The round-11 heal loop cannot be built.
  `first_leg_walkable` stays as belt and braces for the leg's target tile.
- #133's withholding of a door whose landing walk fails stays (it is about the warp tile, not the
  graph), and its heal-trip check becomes redundant but harmless.

The milestone guard (`node in LINKS or node in links`) reads a pocket name; a pocket the run has
never left routes nowhere, which is the same rule as today at finer grain.

## 6. The direction word

Unchanged. The town-map cell is per map, so every pocket of a map shares it; #139's "the map's own
way on is out of reach" rule is now the statement "the connection's edge is not in this pocket",
which is what `reachable_edge` already computes. Inside the cave the word stays silent and the
frontier word carries the run, which is the division of labour the two facts should have.

## 7. What is deliberately not here

- **No ROM-wide world graph.** The ROM has every map's warps and grid, and a graph built from them
  would know which ladder leads to Route 4 without walking. It would also route a milestone over
  ground the run has never walked, which the base spec forbids ("routed over the graph the run
  walks"), and the direction word already brushes that line. The walked graph plus a frontier word
  is the version that stays on the right side of it.
- **No "leads on to new places".** Tried in round 1 of the frontier work; it drew Jev harder than
  "new" did.
- **No recency word** ("we just came from there"). #142's round-trip mark covers the two-map case
  from the executor's side; a word is a separate idea if the marks prove insufficient.
- **No change to what counts as "new" for an NPC, an item or the grass.**

## 8. Testing

Unit:

- pockets: a grid with two components yields stable ids in `(y, x)` order; tile pairs split; a
  one-component map keeps the plain name; a named map keeps its name whatever its grid.
- `node_of` with and without a grid; `map_id_of` on `map_60_p2`.
- `Memory`: a crossing between pockets records pocket-named links and the landing; `from_dict` on
  a pre-change file (old `exits`, `ladders`, no `landings`).
- `leads_nowhere_new`: a building; a B1F pocket with an untaken ladder beyond; a B1F pocket whose
  subtree is all taken; the search stopping at an outdoor map; never passing back through here.
- options: from a 1F pocket with no recorded way out, no heal trip is offered; with the entrance
  pocket's crossing recorded from *another* pocket, still none; from the entrance pocket, offered.
- the explore question's gloss.

ROM (skipped without the state): a Mt. Moon B1F checkpoint copied by hand from a probe run, like
`states/disabled.state`: the floor has more than one pocket, the player's pocket has exactly the
two ladders the run saw offered, and `node_of` names it `map_60_p<k>`.

## 9. How we will know

Round 12: one fresh and one resumed run, 15 minutes, on main with this. Expected:

- zero heal trips offered from a pocket that cannot start them (the round-11 loop gone);
- `visited, leads nowhere new` on B1F ladders whose subtree is exhausted, and never on one with an
  untaken ladder beyond;
- whether any run reaches B1F's exit pocket and Route 4's east side, and how many decisions it
  takes. A null result on that last point is still reportable: it would say the frontier word is
  not enough and the cave needs the direction fact the town map cannot give.
