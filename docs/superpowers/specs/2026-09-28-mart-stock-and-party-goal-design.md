# The Mart says what it sells, and the overworld knows the party goal

Issue #110. Amends `2026-09-21-generated-options-design.md` (option text) and the explore state.

## Why

In the five-run series 2 measurement Jev never caught a Pokémon: 0 of 436 wild battles happened
with a Poké Ball in the bag, so `catch` was never asked; the bag was empty on 244 of 249 overworld
decisions; a Mart was offered 25 times and never chosen. Nothing Jev sees in the overworld says
what a Mart is for, and the standing goal "Build a party of three and keep them healthy" is only
shown in battles, where there is nothing to catch with. #52 tried a "supplies" word keyed to the
bag and was reverted: at the Viridian Mart, which sells no Potion, the word never went away and
Jev walked in and out 674 times. This design adds facts, not a verdict, and nothing that shopping
can fail to discharge.

## What changes

1. **A Mart's door and its clerk say what the shop sells**, in the game's own item names:
   `enter Viridian Mart, which sells POKE BALL, ANTIDOTE, PARLYZ HEAL, BURN HEAL`, and inside,
   `talk to the clerk behind the counter to buy POKE BALL, ANTIDOTE, PARLYZ HEAL, BURN HEAL`.
   The list is read from the ROM's Mart inventory table (`script_mart` data: `0xFE`, a count, the
   item ids, `0xFF`), located per map in `emulator/ram.py`:
   Viridian Mart (map 42) at `0x2442`, Pewter Mart (map 56) at `0x2449`, both in bank 0 and
   matching the shelves the ROM tests already read at the counter. A Mart with no known address
   keeps its plain text. Option ids and memory words are unchanged.
2. **The explore state carries the standing goal**: a `standing_goal` key holding
   `goals.STANDING_CLAUSE` ("Build a party of three and keep them healthy."), the same sentence the
   battle goal already appends. The explore question's instructions name it alongside `progress`
   and `milestone`.

Nothing is routed or ranked. What to buy stays the clerk macro's (`shop.restock`: balls first,
then Potions), whether to go is Jev's.

## Fixtures

Both are wording Jev sees: `explore_viridian` (and any fixture whose options include a Mart or a
clerk) is re-recorded with `Scripts/record-fixtures.py` in the same PR.

## Measuring it

Eight unpaced runs from `states/route1.state` on this code, against series 2's five (which had
none of this). Counted from each run's log and final checkpoint: Mart entered, clerk used, Poké
Balls bought, `catch` asked and taken, party size at the Brock fight, badge, blackouts. A null
result (Jev still walks past the Mart with the goal and the shelf in front of it) is worth having.
