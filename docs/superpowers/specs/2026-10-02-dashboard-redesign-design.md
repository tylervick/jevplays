# The dashboard, redesigned: a page that shows Jev judging and code executing

Date: 2026-10-02
Status: design. Amends section 10 of `2026-09-20-jevplays-design.md` (the page), and closes #12.

## 1. What the page is for

A viewer who opens https://jevplays.fly.dev/ with no context should see, within seconds, that
an AI is judging and code is executing, and should be able to follow one decision as it
happens: what Jev was asked, what it answered and how sure it was, and what code did about it.

That is the whole brief. The page is the window onto "Jev judges, code executes"; everything on
it either shows one side of that line, shows the handoff across it, or is in the way.

Constraints that bind, unchanged from the original design and the public-demo design:

- The page only displays what the loop already publishes. Nothing here changes what Jev is
  asked or shown, so no fixture is re-recorded.
- The WebSocket protocol, `--max-viewers`, and pause-when-unwatched keep working. Additions
  below are new fields on existing events and one new behaviour on connect; nothing is removed
  or renamed, so an old page against a new server, or the reverse, still runs.
- The demo is public: the page stays read-only, with no control that affects the run.

## 2. The page today, evaluated

Measured on 2026-10-02 against the live demo, a replay of demo run `20261001-224054` (472
decisions), and fixed scenes served from `states/battle_wild.state` and `states/route1.state`,
at 1920, 1440, 1280 and 390 pixels wide, in both colour schemes, and as `?layout=stream`.

### 2.1 Nothing says who is deciding and who is executing

The page reads `Jev plays Pokémon`, then `DECISION`, `GOAL`, `LOG`, `State`. The word "Jev"
appears in the title and in the model id at the bottom of the panel (`jev-1.13.0 · 85 ms · 952
tokens`), nowhere else. The one line that says what *code* is doing is the status pill at the
top right, far from the screen it describes, prefixed with the status word every time
(`running: grass: wander`, `running: pressing: throw a Poké Ball`, `running: checkpoint 25`).
A viewer has to already know the project to read the page as two actors.

### 2.2 The options are ids, not what Jev was shown

An explore decision's bars read `grass 65% · milestone 15% · npc_1 12% · exit_east 7% · npc_2
1%`, and at Pallet Town `door_40 56% · npc_1 43% · milestone 1% · door_37 · npc_2 · door_39 ·
npc_3 · exit_south · exit_north`. The words Jev actually saw ("talk to a youngster to the
north-west (new)", "enter Oak's Lab (new)") are in the same event, in
`state_summary.options`, and the page never reads them. The chosen option's text reaches the
headline, so a viewer learns what won but not what it beat.

### 2.3 The question is a wall of prompt text

Each question's `instructions` is printed in full, in 13px muted text, between the headline and
the bars. The explore question is about 900 characters: at 1280 wide it is six lines, on a phone
fifteen, and the bars sit below it. The text is the exact wording Jev saw, which matters and
should stay reachable, but it is not what a viewer needs first.

### 2.4 The panel lags the screen, and there is no moment of deciding

The latest decision stays up until the next one. In a paced run the explore decision ("train in
the tall grass here") is still the panel's headline while a wild battle has already started on
the screen; the first battle decision replaces it a few seconds later. Nothing says how old the
card is. And the decision arrives finished: Jev answers in about 100 ms, so there is no
"asking" phase to show, but the page does not even mark the arrival. A viewer looking at the
screen misses the new card; a viewer looking at the card does not know it changed.

### 2.5 The goal line is empty for a late joiner, and stale after a milestone (#12)

The goal line is set only by explore decisions and cleared only by a `milestone done` status.
A tab opened during a battle (the Broadcaster sends the latest event of each type, and the
latest decision is a battle turn) shows `GOAL –` until the battle ends. Replay never sends the
`milestone done` status, so the line goes stale there. Every decision's `state_summary` carries
the goal (`milestone` and `standing_goal` for explore, `goal` for battle, prompt and starter),
so the line never needs to depend on the decision's kind.

### 2.6 The log is kinds and numbers

`battle: use BUBBLE (0.48)` -- the number is Jev's choice confidence, unlabelled, next to bars
that show percentages. The list is newest-first but numbered by the `<ol>`, so it counts up from
the top, and `padding-left: 20px` clips every marker to `l.` or `.` at every width tested. Each
line names the kind and the action and nothing of the context (which battle, which map).

### 2.7 Hierarchy and the bars

The screen is fixed at 640px and the panel takes the rest, so at 1920 wide a two-option choice
draws bars 900px long for `TACKLE 77%` and `TAIL WHIP 23%`. The headline is 17px, the same
weight as the question ids. Unused questions are dimmed to 45%, which is right, but they are
printed in the order the brain asked them, so when the policy acts on `catch` the dimmed `move`
is still first and `catch` is fourth. `confidence 0.26` on a dimmed question draws the eye to a
number that did not decide anything. The faint prediction's `prediction` badge is correct and
the only place the page explains itself.

### 2.8 Battle and overworld look the same

One panel serves both, which is right, but nothing on the Jev side says the situation: a
battle card does not name the opponent, an explore card does not name the map, though
`state_summary` has both (`enemy_pokemon.name`, `level`; `map`). The party strip under the
screen carries nickname, level, and an HP bar, and that is enough.

### 2.9 Phone width

The page does collapse to one column and the screen scales to the width, which is the hard
part, but: the status pill wraps to two lines and shares the header with the title; the split
bars clip their left label (`yes 1` for 14%); the explore prompt is fifteen lines; and the
State readout, with raw JSON and tile coordinates, is a tap away on a public page.

### 2.10 Dark only, and all monospace

`prefers-color-scheme: light` is ignored; the light screenshots are identical to the dark
ones. Every string on the page, including the prompt paragraph and the goal sentence, is in the
monospace stack, which is what makes the prompt text read as a terminal dump.

### 2.11 Pausing, waking, disconnecting, full

Before the socket opens the pill reads `stopped` in red (the HTML default), so the first thing
every viewer sees is a dead-looking page. Then the Broadcaster's latest status arrives: on the
public demo that is `unwatched: nobody is watching; it carries on when someone opens the page`,
shown to the person who just opened it, replaced by `someone is watching` a moment later.
Nothing explains that the game paused *because* nobody was watching and is waking up for them.
On a disconnect (a deploy restarts the Machine about once a day) the last frame stays up,
unchanged, with only the pill reading `disconnected, retrying…`; the same for `the demo is
full`. A frozen frame under a green-looking page is the one state that should never be
ambiguous.

### 2.12 Replay

The screen area is black, the party strip empty, the State block says `waiting for the first
snapshot…`, and the only sign that this is a replay is the pill: `running: replaying
20261001-224054: 27/472`. The goal line goes stale (2.5).

### 2.13 The stream layout

`?layout=stream` works as a 1920x1080 canvas and shares every problem above; the lower third of
its right column is empty.

### 2.14 What is right and stays

The game screen at an integer scale with nearest-neighbour filtering; the party strip; one bar
per option, the winner highlighted, the probability as the label; the yes/no split bar for a
Noul; dimming what the policy did not use; the `prediction` badge on `faint`; the headline
being the action in words; `finished` having its own colour (#29); the tab letting go of its
socket when hidden so the run can pause; and the `#status` element's `data-status`, which
`Scripts/record-demo.py` reads to know when a recording is over.

## 3. The design

### 3.1 One sentence, two actors, one handoff

The page is a stage with two sides. Left, **the game**: the screen, the party, and one line
saying what code is doing right now. Right, **Jev**: the question it was asked, in a few
words, the options as it saw them, its answer with the probability it gave each one, and the
line that hands the answer back to code. Under the title, one sentence that a stranger reads
first: *Jev, an AI model, answers narrow questions about the game. Code reads the game's
memory, asks, and presses the buttons.*

Desktop, 1000px and wider:

```
Jev plays Pokémon                                                  [● live]
Jev, an AI model, answers narrow questions about the game. Code reads the
game's memory, asks, and presses the buttons.

┌ THE GAME ─────────────────────┐ ┌ JEV ────────────────────────────────────────────┐
│                               │ │ battle · SQUIRTLE L9 vs a wild WEEDLE L3 · 4s ago │
│   [screen, 160x144 scaled]    │ │                                                   │
│                               │ │ Throw a Poké Ball?                      acted on  │
│                               │ │ yes ██████░░░░░░░░░░░░░ no          35% · 65%     │
│                               │ │                                                   │
│ SQUIRTLE L9  ████████░░ 27/38 │ │ Which move?                    not used · 0.52    │
│ PIDGEY L4    ██████████ 17/17 │ │ ✓ BUBBLE          ████████████████████  76%       │
│                               │ │   TACKLE          ██████                24%       │
│ CODE IS: throwing a Poké Ball │ │                                                   │
│ GOAL: Challenge Brock at the  │ │ also asked  switch? no 88%  run? no 88%           │
│ Pewter Gym and earn the       │ │ prediction  faint before next turn? 8%            │
│ Boulder Badge. Build a party  │ │                                                   │
│ of three and keep them        │ │ → code presses: throw a Poké Ball                 │
│ healthy.                      │ │ jev-1.13.0 · 103 ms · 693 tokens · the question   │
│                               │ │   as Jev saw it ▸                                 │
│                               │ │                                                   │
│                               │ │ RECENT                                            │
│                               │ │ throw a Poké Ball       yes 35%   battle          │
│                               │ │ use BUBBLE              76%       battle          │
│                               │ │ train in the tall grass 65%       explore         │
└───────────────────────────────┘ └───────────────────────────────────────────────────┘
```

The screen keeps its integer scale (4x at desktop, 6x on the stream canvas) and the Jev column
takes the rest, capped at about 760px so bars stay readable; the two columns are centred as a
pair on wider windows instead of the panel stretching to the window edge.

### 3.2 The Jev card

One card, replaced on every decision, built from a `view` the server attaches to each decision
event (3.6). Top to bottom:

1. **Where.** The kind as a tag (`battle`, `explore`, `prompt`, `menu`, `starter`) and the
   situation in words from `state_summary`: `SQUIRTLE L9 vs a wild WEEDLE L3`, `SQUIRTLE L9
   vs a trainer's GEODUDE L12`, `on Route 1`, `the prompt "give a nickname to
   PIDGEY?"`, `at Oak's table`. Then how old the card is, `4s ago`, ticking, from the decision's
   `ts` against the page's clock offset (3.8).
2. **The questions, acted-on first.** Order: questions the policy applied, then the ones it
   did not, then the `faint` prediction last. Each has a short label in plain words (3.6) with
   its tag: `acted on` (shown only when more than one question was asked), `not used`, or
   `prediction`. Unused questions are dimmed as today.
   - A Choice: one row per option, sorted by probability, the chosen option first with a check
     mark. The label is the option's text as Jev saw it: `state_summary.options[id]` when the
     answer's option ids are keys there (explore), else the id itself (moves, species, bench
     names). An explore option's trailing memory word (`new`, `visited`, `tried`, `talked
     already`) is split off into a small tag so the bar label stays short. The bar is the
     probability; the figure sits at the row's right edge. Jev's choice confidence is a muted
     `confidence 0.52` chip on the question's header line, kept because it is Jev's own number,
     not promoted.
   - A Noul: one split bar, `yes` share filled from the left, `no` the rest, with the two
     percentages at the ends of the row outside the bar, never inside it, so they cannot clip.
3. **Also asked.** Unused Nouls collapse into one line of chips (`switch? no 88%`, `run? no
   88%`), and an unused Choice shows only its top option (`switch to PIDGEY 100%`), each
   expandable to the full bars with one click. A six-question battle turn then fits on a phone
   screen with the acted-on question and its bars in full.
4. **The handoff.** `→ code presses: throw a Poké Ball` for a battle, `→ code walks: enter
   Oak's Lab` for explore, `→ code answers: NO` for a prompt, `→ code selects: …` for a menu,
   `→ code takes: SQUIRTLE` at Oak's table. When no model answered (`model` is empty: the
   never-nickname policy, an offline run), the line reads `→ code decided on its own: policy:
   never nickname` and the card has no bars; the kind tag reads `code` instead of `jev`.
5. **Meta.** `jev-1.13.0 · 103 ms · 693 tokens`, muted, and a `the question as Jev saw it`
   disclosure that opens the full `instructions` of every question in the order asked, in a
   serif-free prose face. Nothing Jev saw is hidden; it is one click down instead of first.

On arrival the card's bars grow from zero to their widths over 300ms and the card's edge
flashes once, so a viewer watching the game notices the decision land. The `ago` counter is
what tells a viewer the card is older than what the screen shows (2.4).

### 3.3 The game side

Under the screen, in this order:

- **The party strip**: nickname, level, HP bar in the bucket's colour, `hp/max`, and the
  status condition when there is one. Unchanged except for colour tokens.
- **Code is:** the status message, in its own line, labelled. The status *word* moves to the
  header pill (3.4); this line carries only the message. Two messages are filtered: `checkpoint
  N` and `someone is watching` are housekeeping, so they go to a small muted note under the line
  (`saved checkpoint 25`) instead of replacing what code was doing. The messages themselves stay
  as the loop writes them; wording the macros in plainer words is a loop change and is filed
  separately (3.9).
- **Goal:** the active milestone and the standing goal, from every decision's `view.goal`
  (3.6), so a late joiner sees it on the first event and replay keeps it current. A `milestone
  done` status still clears it between decisions, as today.

### 3.4 The run's state: the pill and the screen overlay

The header pill shows a dot and a word, from `data-status`, in the reserved status colours:

| status          | pill            | colour   |
|-----------------|-----------------|----------|
| (not connected) | connecting      | neutral  |
| running         | live            | good     |
| waiting_for_api | waiting for API | warning  |
| paused          | stuck           | warning  |
| unwatched       | waking up       | neutral  |
| resting         | resting         | neutral  |
| stopped         | ended           | critical |
| finished        | finished        | gold     |
| (socket closed) | reconnecting    | critical |
| (code 1013)     | demo full       | critical |

`#status` keeps its id and `data-status` values (`record-demo.py` reads them; `connecting`,
`reconnecting` and `full` are new values the page sets itself, and the script only looks for
`finished` and `stopped`).

Everything that is not `running` also puts a translucent card over the game screen, because
the screen is where a viewer looks and a frozen frame must never pass for live:

- `unwatched`: *The game paused while nobody was watching. It is waking up for you.* The
  status that follows (`running`) clears it. The stale `unwatched` message is never shown as
  text.
- `resting`: *Today's decision budget is spent. The run rests until 00:00 UTC.*
- `waiting_for_api` / `paused`: the status message as the loop wrote it.
- `stopped`: *The run ended.* plus the message; on the public demo the supervisor starts the
  next run within a minute and the page reconnects by itself, which the card says.
- `finished`: the finish words from the message (*Boulder Badge earned*), in gold.
- socket closed: *Reconnecting…* over the dimmed last frame; `demo full`: *The demo is serving as many
  viewers as it can. Trying again in 30 seconds.* (the cap is not in any event, 3.9).
- before the first frame on a live run: *Connecting…* on a blank screen.
- replay (3.5): the replay card.

### 3.5 Replay

`jevplays replay` publishes decisions and statuses only, so the page detects a replay from the
status message it already pins in tests (`replaying <stamp>: i/n`, then `replayed n decisions`)
and shows, in the screen area, a card: *Replay of run `<stamp>`, decision 27 of 472. The log
kept Jev's decisions, not the video.* The party strip is hidden (no state arrives) and the pill
reads `replay`. The goal line works from `view.goal` (3.3), which closes #12.

### 3.6 The server attaches a `view` to each decision event

`src/jevplays/dashboard/present.py`: `present(decision: dict) -> dict`, pure, tested without a
browser. `decision_event_from_dict` calls it and sets `event["view"]`, so the loop and replay
both carry it, and the replay of any old log gets it too. The decision itself is unchanged.

```
view
  actor: "jev" | "code"              # code when decision.model is empty
  kind: battle | explore | prompt | menu | starter
  where: str                         # "SQUIRTLE L9 vs a wild WEEDLE L3", "on Route 1", ...
  goal: str                          # milestone + standing goal, or goal; "" when absent
  questions: [                       # applied first, unused next, prediction last
    { id, label, instructions, primitive, role: "applied" | "unused" | "prediction",
      confidence,                    # choice only
      options: [{ id, label, memory, p, chosen }],   # choice, sorted by p desc
      yes: p }                       # noul
  ]
  handoff: str                       # "code presses: throw a Poké Ball"
  reason: str                        # decision.fallback_reason
  summary: str                       # one line for the recent list: "throw a Poké Ball · yes 35%"
```

Question labels are a fixed table in `present.py`, keyed by question id: `move` → *Which
move?*, `switch` → *Switch out?*, `switch_to` → *Switch to which?*, `run` → *Run away?*,
`catch` → *Throw a Poké Ball?*, `heal` → *Use a Potion?*, `faint` → *Faint before the next
turn?*, `explore` → *What next?*, `needs_heal` → *Heal first?*, `starter` → *Which starter?*;
an id not in the table is shown as the id with underscores as spaces. The full `instructions`
travel alongside, so the label never replaces the question, only introduces it.

`where` is derived from `state_summary` by kind: battle from `our_pokemon`, `enemy_pokemon`
and `battle.kind` (`trainer_class` is not in the summary, so a trainer battle reads `vs a
trainer's GEODUDE L12`); explore from `map`; prompt from `prompt`; starter is the fixed string
`at Oak's table`; menu from the summary's `menu` text when present. Any missing field makes
the string shorter, never an error.

The option label for a Choice is `state_summary.options[id]` when that mapping exists and has
the id, with a trailing parenthesised memory word split into `memory`; otherwise the id.

### 3.7 Late joiners get the recent decisions

`Broadcaster` keeps the last 10 decision events in a deque and, on connect, sends them oldest
first after the latest frame, state and status, so a new tab's Recent list and Jev card start
populated. The latest-per-type behaviour is unchanged for every other type. Each decision is
still sent once to a connected tab.

### 3.8 Clock offset for "ago"

A decision's `ts` is the server's wall clock. The page keeps `offset = Date.now()/1000 - ts` of
the most recent decision, clamped at zero on the live run (the decision cannot be in the
future), and shows `max(0, now - ts - offset)`. On a replay the decisions' timestamps are days
old, so `ago` is hidden whenever the replay card is up.

### 3.9 Out of this change, filed as issues

- #144: the loop's status messages are written for the log, not a viewer (`grass: wander`,
  `option: go north to Route 2`, `npc_3: talk`). Plain words for what code is doing is a loop
  change.
- #145: resolved faint predictions (`outcomes.jsonl`) are never published, so the card cannot
  say whether the last prediction came true. An `outcome` event would let it.
- #146: the viewer cap is not in any event, so the "demo full" card cannot say the number.

### 3.10 Layouts

- **Desktop (≥1000px):** two columns as drawn, the game side `max-content` wide at 4x, the
  Jev column `minmax(0, 760px)`, centred together.
- **Phone (<1000px):** one column. Header: title and pill on one line, the sentence under it.
  Then the screen at full width (`image-rendering: pixelated`), party, `code is`, goal, the Jev
  card, recent. Choice rows put the label above the bar so a long explore option wraps instead
  of truncating; split bars keep their figures outside the bar.
- **Stream (`?layout=stream`):** 1920x1080 fixed as today, the screen at 6x (960x864) with the
  party strip and the two lines beside it under the screen, the Jev card and the recent list
  filling the right column; the disclosure and the debug block hidden.
- **Debug:** the raw state readout (mode, map and tile, text, menu, flags, JSON) stays for
  development behind `?debug=1`; it is not on the public page.

### 3.11 Colour, type, motion

Tokens on `:root` with a dark set under `prefers-color-scheme: dark`, both selected, not a
flipped palette. Prose and labels in the system sans stack; monospace only for ids, the model
line, and the debug block. Probability bars are one hue: the chosen option in the accent
(blue), the rest in a neutral fill, at most 16px thick, rounded at the data end, square at the
baseline, a 2px gap between rows. HP bars and the pill use the reserved status colours (good,
warning, serious, critical) with the word beside them, never colour alone; `finished` keeps its
gold. The bar-growth and card-flash animations are the only motion, both under
`prefers-reduced-motion: reduce` disabled.

### 3.12 Testing

- `tests/test_present.py`: `present()` on recorded decisions of every kind from
  `tests/fixtures/` and the demo logs in this spec: ordering of questions, option labels from
  `options`, the memory word split, `where` per kind, `goal` per kind, `actor: code` on a
  model-less decision, `summary` wording, and that a decision missing any summary field still
  presents.
- `tests/test_events.py`: a decision event carries `view`.
- `tests/test_server.py`: a late joiner receives the recent decisions oldest first, after the
  latest of the other types; the page serves and references the static files.
- The page itself is checked by eye with Playwright screenshots at the four widths and both
  schemes (the script that produced section 2's screenshots), not in CI: there is no browser
  on the runner and the house rule keeps CI free of one.

## 4. Not in this change

- Any change to what Jev is asked or shown.
- Publishing new event types (outcomes, viewer counts): filed (3.9).
- A viewer-facing control of any kind.
