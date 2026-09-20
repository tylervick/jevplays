Gen 1 lookup tables, keyed by the game's internal ids as JSON strings.

- `species.json`: internal species id (not Pokédex number) to display name. 154 entries.
- `moves.json`: move id to `{name, type, power, pp}`. 165 entries, from pokered's `data/moves/moves.asm`.
- `items.json`: item id to display name. 81 entries.
- `trainers.json`: trainer class id to name (`RIVAL1` is 25). 48 entries.
- `events.json`: event flag name to bit index in `wEventFlags`, 507 entries, from PyBoy's Gen 1 constants.

Names come from PyBoy's Gen 1 constants (which follow pokered) with underscores replaced by
spaces so they match what the game prints. Type ids are few enough to live in `names.py`.
