# The map graph the run builds: routing past the hand-written table (#35)

**Status:** approved design, 2026-09-22. Amends `2026-09-21-generated-options-design.md` sections 2 and 3, and `2026-09-20-jevplays-design.md`'s routing. The base spec's rules all still apply: Jev judges, code executes; no raw numbers, coordinates, or screenshots reach Jev; counters stay scripted.

## 1. Purpose, and what this is not

`executor/maps.py` holds a hand-written graph of 19 nodes that stops at Pewter. `maps.route` searches it and nothing else, so `legs_to` can only plan a journey between places somebody typed in. Standing on Route 3 today, the run gets **no milestone option** (`_milestone_option` bails on a `map_` node) and **no heal option** (`_heal_option`'s `maps.route` returns `None`). It can walk east; it cannot come back.

**This is consolidation, not reach.** The issue was shaped as the thing standing between the project and a second badge, and the measurement disagrees. With #53 and #55 fixed, exploration alone carries a run Pewter → Route 3 → Mt. Moon 1F → Route 4, one map from Cerulean, with `maps.LINKS` untouched — because `_exit_options` already reads connections from RAM every turn. Forward reach was never the graph's problem; it was two livelocks.

What the graph is for is the return path: a run that walks east can heal, shop, and resume its milestone instead of blacking out and losing the ground it took. That is worth building. It is not a second badge, and this spec does not claim to be one.

**A RAM-derived graph can never route to somewhere unvisited.** `read_connections` reports the map the player is standing on. From Pewter you learn "east → map 14" and nothing about what lies beyond it, so routing a milestone to Cerulean stays impossible until a run has walked to Cerulean. Any design that appears to promise otherwise is promising a speculative route. We are not building one.

## 2. Where the links come from: crossings, not connection tables

The shaped issue proposed recording each map's connections and warps on arrival. This design records a link **when the run actually crosses it**, for three reasons:

1. `read_connections` reports the whole map's connections, not the ones reachable from where you stand. Route 2's two halves both report `north → Pewter`, while `reachable_edge` finds no north edge from the south half — so the table would add a shortcut the navigator then fails to walk, and the option would be marked `tried` for a route that was never real.
2. A warp's `dest` is `0xFF` (`WARP_LAST_MAP`) for "back out the way you came in", which names no map. A crossing knows both ends.
3. A crossing is ground truth. Nothing else has to be filtered, resolved, or trusted.

The cost is that the graph grows with movement rather than with arrival. For a return path that is exactly right: you got there somehow, so the way back is what you want, and you have just walked it.

### 2.1 Edges are recorded in both directions

Gen 1 overworld connections are symmetric, so crossing `A --east--> B` records `B --west--> A` as well. Without this the return path would need a second walk to learn, which defeats the purpose. A warp `A --warp(dest=B)--> B` records the reverse as `B --warp(EXIT)--> A`, which is how `LINKS` already encodes a building's way out.

## 3. Node names, not map ids

The issue flags one design decision: the recorded links are map ids, while `LINKS` is keyed by node name. This design **synthesises node names** and leaves `Leg` untouched.

`maps.node_of(map_id, x, y)` already returns `map_<id>` for a map with no name, and `MAP_IDS`'s docstring already says a node with no entry is simply absent and its leg carries no `dest_map`. The convention exists; this uses it.

Deriving the node from `node_of` at the moment of crossing also disambiguates Route 2 for free — a map-id-keyed overlay cannot, because one id covers two nodes.

`maps` gains `map_id_of(node)`: `MAP_IDS` when present, the integer parsed out of `map_<id>` otherwise, and `None` for neither. Edge legs use it for `dest_map`, so a blackout mid-walk still reads as `lost` rather than as arrival (#8's concern, unchanged).

## 4. Data

`Memory` (in `executor/options.py`, alongside `visited_maps`, `talked` and `tried`) gains:

```python
links: dict[str, list[Link]]      # from-node -> the links crossed out of it
```

`to_dict` writes it as JSON-safe tuples; `from_dict` reads it with `.get("links", {})`, so a `memory.json` written before this change loads unchanged and simply starts empty. `runs/<stamp>/memory.json` is the same file it always was and `--resume` keeps working.

`note_crossing(from_node, to_node, *, direction=None, dest_map=None)` records one crossing as two links -- the one just walked and its reverse (section 2.1) -- and is idempotent. `direction` is set for an edge, `dest_map` for a warp; the reverse of a warp is `warp(WARP_LAST_MAP, from_node)`. Nothing is ever removed: a link that was crossed once was real.

## 5. Routing over the union

`maps.route(from_node, to_node, links=None)` searches `LINKS` and the overlay together. Where both have a link out of the same node, **`LINKS` is searched first** — it carries the node names, the Route 2 split, and the leg labels, none of which RAM gives you, and it is the curated answer where it exists.

`legs_to(state, dest_node, links=None)` passes the overlay through.

`Goal.legs` becomes `Callable[[GameState, dict[str, list[Link]]], list[Leg]]` — every milestone's legs function takes the overlay. A uniform signature is worth more than an optional one here: three functions in `goals.py`, and the alternative is module-level mutable state that `route` reads behind the caller's back.

`options.generate` already holds the `Memory`, so `_heal_option` and `_milestone_option` pass `memory.links` down.

## 6. What this lets go of

`_milestone_option`'s `node.startswith("map_")` guard is removed. It exists because an unmapped node could never route; with the overlay it can. Removing it is only safe because **#53 landed first**: a milestone that still cannot be routed now has no legs and no macro, so it is not offered at all, rather than being treated as arrived. The two changes are complementary and this one depends on that one.

`_heal_option` keeps its shape. It gets more useful for free: a Center becomes reachable from anywhere the run has walked back from.

## 7. What is deliberately not here

- **No speculative frontier hop.** A connection to a map nobody has entered is not a routable edge (section 1).
- **No replacement of `LINKS`.** It stays as the curated layer, and as the thing that makes Route 2 and the building labels work.
- **Nothing new reaches Jev.** The options and their words are unchanged; what changes is which of them can be built. `maps.route` is code's arithmetic, which is where the base spec puts it.
- **No new RAM reads.** `read_connections`, `read_warps` and the navigator's own map checks are all already there.

## 8. Testing

Unit, over a synthetic `Memory`:

- a crossing records the link and its reverse; recording twice is idempotent
- `route` finds a path that needs one overlay link, one `LINKS` link, and a mix
- `LINKS` wins where both have a link out of the same node
- `map_id_of` on a named node, a `map_<id>` node, and a node that is neither
- `legs_to` over the overlay builds edge legs carrying `dest_map`
- a milestone on an unmapped node is offered when the overlay can route it, and not offered when it cannot (the #53 interaction)
- `Memory.from_dict` on a dict with no `links` key

ROM, under `tests/rom/` and skipped without the save states: a run that has crossed Pewter → Route 3 can route a heal trip back from Route 3 to the Pewter Pokémon Center.

## 9. How we will know it worked

Four unpaced runs from `states/brock_award.state` with the throwaway probe milestone that #53 and #55 used, before and after:

- **maps visited**, and how far east the run gets
- **heal options offered outside `LINKS`** — zero before, by construction
- **blackouts past Pewter**, which is what the return path is supposed to prevent
- decisions to the same point, to see what the routing costs

A null result is reportable: if a run that can now route home does not choose to, that is a fact about what Jev weighs, and #52 has just shown the same shape of answer is worth having.
