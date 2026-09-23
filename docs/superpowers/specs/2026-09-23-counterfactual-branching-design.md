# Counterfactual branching

Issue #82. A measurement tool. It changes nothing Jev is asked or sees.

## The question

Every number the project has published so far is about calibration (#17, #42, #68): when Jev says
0.47, does the thing happen 47% of the time. None of them asks whether the choice Jev made was
better than the ones it passed on. This tool answers that: at a decision Jev made, play every
alternative the game allowed from the same state, let Jev play each branch on to the milestone,
and compare how long each took.

The deliverable is a headline number that sits beside the calibration numbers in the README: mean
regret in seconds of game time, with a confidence interval, for battle and explore decisions
separately, next to the same number for simple first-action rules. The per-decision table the
number is computed from doubles as a debugging view, for telling a bad judgment from bad luck.

Not in scope: showing branches live on the dashboard. Every live decision would cost K times the
alternatives in rollouts and would spend the demo's daily budget.

## Shape

Two steps, run separately.

1. **Record.** `jevplays run --snapshot-every-decision` saves the game and the run's memory at
   every decision, after it is logged and before its buttons are pressed. That is the point
   `Loop._record` already checkpoints at, every 25 decisions.
2. **Branch.** `jevplays branch runs/<stamp>` picks decisions from that run and, for each one,
   runs every alternative with K random seeds in parallel processes, one PyBoy each. Each branch
   is a headless `Loop` rebuilt from the snapshot, with the first action forced and Jev playing
   everything after it. Results go into `runs/<stamp>/branches/branches.sqlite`.
   `Scripts/branch-report.py` reads that file.

The logged run is never modified, and a run recorded today can be branched again later, for
example against a new model or with more seeds.

Branching during the run was considered and rejected: a measurement run could not also be a
normal run, a failing branch could take the run down, and a decision could not be looked at
again. Rebuilding each decision point by replaying from the nearest 25-decision checkpoint was
also rejected: it saves 17 MB a run in exchange for depending on an exact replay, and any
difference (a timeout, a changed prompt) silently moves the branch point.

## Snapshots

`--snapshot-every-decision` writes `runs/<stamp>/snapshots/<n>.state` (the emulator,
`Emulator.save`) and `runs/<stamp>/snapshots/<n>.memory.json` (the `Memory` as `_save_memory`
writes it), where `n` is the decision's number in `decisions.jsonl`. A snapshot is 168 KB, so a run
to Brock with about 100 decisions costs about 17 MB. Snapshots stay files: PyBoy loads state
from a file object and nothing searches them.

The in-progress option is not saved. A battle decision often happens partway through an option,
such as wandering the grass. `--resume` does not restore that option, so after the battle a
branch asks Jev for a fresh option where the logged run carried on with the old one. Every
alternative of the decision starts from the same point, so the comparison is fair, but a branch
is not a perfect copy of the run's future. Saving the option is the same "state beyond the
emulator" problem as #8 and is not attempted here.

## Forcing the first action

A branch builds its `Loop` the way `--resume` does, from the snapshot and its memory, with a new
`forced` argument holding one `BattleAction` or `ExploreAction`. At the first battle menu or
explore turn, the loop uses `forced` instead of calling `_decide`, and then clears it:

- `_battle_turn` takes the forced action through `_resolve_switch` and `battle_macros.apply`,
  exactly as it would take one of Jev's.
- `_choose_option` takes the forced option id from the freshly generated list and calls
  `_start_option`.

The forced action is logged as a decision with `forced=True`, so a branch's log reads like any
other run's. Every later decision is Jev's, asked the normal way through the response cache.

## Alternatives

`src/jevplays/branch/alternatives.py` lists them from the snapshot's `GameState`. These are game
rules, so code owns them.

Battle: every action the game would accept at that menu.

- `move:<name>` for each move with PP left (every move if all are out, as in `battle_questions`)
- `run` in a wild battle
- `catch` in a wild battle when the bag holds a Poké Ball
- `heal` when the bag holds a Potion and the lead is below full HP
- `switch:<label>` for each bench member that has not fainted, labelled as in `bench_slots`

Explore: every option `executor.options.generate` returns for the snapshot's emulator, memory and
milestone.

Fidelity check. A snapshot must rebuild the decision point exactly. For an explore decision, the
generated option ids must equal the ids in the logged `state_summary`. For a battle decision, the
rebuilt state summary must equal the logged one, and Jev's logged action must be among the
alternatives. A decision that fails either check is skipped and counted as "not reproducible".
Nothing is ever branched from a state that differs from the one Jev saw.

Not branched: prompt and menu decisions (mostly yes/no boxes that policy settles), and decisions
code made without Jev (`fallback=True`).

## Seeds

The game's random numbers are fed by a hardware timer that ticks every frame, and PyBoy is
deterministic. Loading a state and pressing the same buttons replays the same damage rolls,
misses and critical hits. Seed `s` of a branch therefore ticks `s` idle frames after loading and
before the forced action. Every alternative of a decision runs on the same seeds 0 to K−1,
including the action Jev actually chose. The logged run is not counted as a branch, because its
randomness was not controlled the same way.

## When a branch stops

A branch stops at the first of:

- **done**: the milestone that was active at the snapshot is complete, meaning
  `goals.active_milestone` no longer returns it.
- **capped**: the branch has spent 3× the game frames the logged run took from that decision to
  the same milestone. Game frames, not wall-clock time, so the #61 problem does not come back.
  A decision whose logged run never finished that milestone is skipped and counted as "no
  reference".
- **stalled**: 20,000 game frames with no new decision, which is five and a half minutes of game
  time. This bounds the #67 hang, where the loop presses A in BATTLE_WAIT forever.

A branch's score is the game frames from the snapshot to **done**. A blackout is not given a
penalty: it already costs real frames (the warp to the Pokémon Center, the walk back, the fights
again), and those frames count. Blackouts are reported as their own count beside the score.
Capped and stalled branches have no score. The analysis treats them as censored ("at least the
cap"), and the report says how many there were.

## The response cache

`src/jevplays/brain/cache.py` adds `CachedBrain`, which wraps a brain and has the same
`ask(state, questions)` interface. The loop cannot tell the difference, and `import typesafe_sdk`
stays in `brain/client.py` alone.

- Key: SHA-256 of the canonical JSON (sorted keys) of the requested model name, the state and the
  questions.
- Value: the raw response and the model it reports, in the `response` table of
  `branches.sqlite`.
- A cache hit is logged on the decision as `cached=True` with the original latency, so reports
  can tell real calls from replayed ones.
- If a real response reports a different model from the one the logged run recorded in
  `run.json`, the measurement stops and says so, rather than comparing two versions of Jev.

The cache rests on one assumption, and the first step of the plan checks it: the same input gets
the same answer. Twenty logged inputs are each sent to the real API five times and the
probabilities compared. If they are identical, the cache changes nothing. If they vary, the
cache still keeps a measurement consistent, because every branch of a decision faces the same Jev,
but the result then measures one sample of Jev per input rather than its average. The report
prints the variation found either way.

## Storage

One SQLite file per measurement, `runs/<stamp>/branches/branches.sqlite`, in WAL mode, written
by every branch process:

- `branch`: decision number, alternative, seed, outcome (`done` | `capped` | `stalled`), frames,
  blackouts, Jev calls, cache hits, and when it finished. One row, written when the branch ends.
- `decision`: branch id, sequence number, and the decision JSON exactly as `decisions.jsonl` would
  hold it.
- `response`: the cache.

Why SQLite rather than a directory per branch: a measurement is about 4,000 branches, and the
decision logs alone come to 200–400 MB across 8,000+ files. An interrupted measurement resumes by
skipping every (decision, alternative, seed) that already has a `branch` row, where a half-written
directory would look finished. The report and the per-decision view become queries. SQLite ships
with Python and handles several processes writing at once. DuckDB would be faster for analysis but
adds a dependency that 4,000 rows do not need. Revisit it if later experiments query branch data
at larger scale.

`branch-report --export <branch>` writes one branch out as an ordinary run directory, so
`jevplays replay` plays it on the dashboard unchanged.

The normal run log stays `decisions.jsonl`. The dashboard, `--resume`, the demo watchdog and
`Scripts/accuracy.py` all read it. Measurements live under `runs/<stamp>/branches/`; the demo's
cleanup only deletes runs in `runs/demo` and never reaches them.

## Scoring

Pure functions in `src/jevplays/branch/score.py`, reported by `Scripts/branch-report.py`.

- An alternative's value is its median frames across seeds. It is marked censored when half or
  more of its seeds did not finish.
- **Regret** of a decision is the median of Jev's chosen alternative minus the median of the
  best alternative, in seconds of game time (frames / 60). Picking the best of several noisy
  medians and scoring it on the same seeds biases it low and makes Jev look worse than it is. So
  the best alternative is *chosen* on the first half of the seeds and *scored* on the second half.
  With K=8, it is chosen on seeds 0–3 and scored on seeds 4–7.
- **Headline:** mean regret over decisions with a 95% bootstrap confidence interval (fixed
  bootstrap RNG), and the share of decisions where Jev's choice was the best or tied with it.
  Tied means the 95% bootstrap interval of (chosen − best), taken over the scoring seeds,
  includes zero. Battle and explore are reported separately.
- **Baselines** use the same data, with no extra runs. Every alternative was branched, so the
  regret of any rule for picking the *first* action can be read off: a uniformly random
  alternative, the highest-power move (battle), and `Loop._offline_option`, milestone first
  (explore). Like Jev's choice, a baseline differs only in the first action, and Jev plays
  everything after it.
- `--decision <n>` prints one decision's table: each alternative's median, spread, blackouts and
  censored count, with Jev's choice marked.
- Every report opens with its counts: decisions, K, not reproducible, no reference, capped,
  stalled, Jev calls against cache hits, and the model.

## Defaults

`jevplays branch` branches every battle and explore decision Jev made in the run, with K=8.
`--sample N` picks N decisions at random (fixed RNG), and `--seeds K` sets K. `--workers` sets
how many branch processes run at once and defaults to the CPU count. Quota is not a constraint
for this measurement. The report's intervals show whether K was large enough.

## Testing

Unit tests, with no ROM and no API:

- `alternatives`: built `GameState`s for a wild battle, a trainer battle, an empty bag, a fainted
  bench member and PP all out.
- `CachedBrain` against a fake brain: a hit, a miss, the key's sensitivity to each part, and the
  model-drift stop.
- The forced first action in `Loop`, using the existing fakes: the forced action is taken once,
  logged with `forced=True`, and the next decision goes to the brain.
- `score`: median and censoring, the split seeds, a reproducible bootstrap, and each baseline.
- The resume-skip query against a small SQLite file under `tmp_path`.

ROM tests in `tests/rom/`:

- A snapshot taken from a save state passes the fidelity check.
- A forced move is the move pressed.
- A branch from a state near Brock stops as `done` at the badge.

Last, one real measurement of one run, with its report in the PR.
