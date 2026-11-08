# Status: parked as a proof of concept (2026-10-27)

jevplays is not being actively developed. This page records where it stopped so that someone
can pick it up again, or judge it, without reading the git history. Everything here was
checked on 2026-10-27 against `main` at 57a6f2b (the merge of PR #147).

## What works end to end

A run started with `jevplays run` does all of the following, with Jev (TypeSafe's System One
model) making every judgment and code doing everything else (`README.md` has the design
argument; the spec is `docs/superpowers/specs/2026-09-20-jevplays-design.md`, amended by
`2026-09-21-generated-options-design.md`):

- Boots Pokémon Red in PyBoy, plays through the intro or loads a save state, and parses the
  party, the active battle, story flags, the bag, and nearby sprites out of RAM
  (`src/jevplays/emulator/`, `src/jevplays/state/`). Milestones 1 to 3 (PRs #2, #9, #14).
- Lets Jev pick the starter at Oak's table (PR #87).
- Fights: at every battle menu Jev is asked which move, whether to run, whether to heal, catch
  or switch, and gives a faint prediction that code later scores for calibration (PRs #6, #23,
  #24, #54). All five actions execute, including catching with a ball at full HP (PR #120).
- Explores: at every idle overworld turn code generates the options off the map in RAM (exits,
  doors, NPCs, the grass, a heal trip, the active milestone, a Mart that says what it sells),
  Jev picks one, and code walks there over a live walkability grid with A*. Milestone 4b
  (PR #38) and the long tail of navigator fixes after it (#89, #95, #101, #102, #116, #121,
  #122, #126 to #133, #135, #139, #142, #143).
- Reaches the Boulder Badge from the intro without a hand-written route past the three
  milestones in `executor/goals.py`, and can carry on to Misty with `--until beat_misty`
  (PR #123). Mt. Moon and Cerulean are named; routes past Pewter are built from the crossings
  the run walks (PR #64), not from a table.
- Logs every run under `runs/` with decisions, memory, outcomes and checkpoints; `--resume`
  continues one and `jevplays replay` plays one back (PR #14).
- Serves a dashboard with live probability bars, a stream layout for OBS, and a demo mode
  that keeps a run going for viewers (PRs #30, #32, #71, #76, #109).
- Deploys the demo to Fly.io (PR #98, `fly.toml`, `Dockerfile`) with an uptime workflow that
  is inert until the `DEMO_URL` repository variable is set. It is unset today, so nothing is
  monitoring the demo; whether the Fly app is still running was not checked (no `flyctl`
  session on the parking machine).
- Measures: `jevplays branch` replays every alternative Jev passed on from the same saved state
  and `Scripts/branch-report.py` scores it (PRs #90, #93, #96); `Scripts/accuracy.py` scores move
  choice and faint calibration over a run; `Scripts/jev-determinism.py` re-asks logged questions.

The test suite on 2026-10-27, with the ROM and save states present:

| checkout | result |
| --- | --- |
| `main` @ 57a6f2b | 717 passed, 4 skipped |
| PR #155 (`tylervick/pocket-places`) | 720 passed, 3 skipped |
| PR #156 (`tylervick/ui-redesign`) | 731 passed, 4 skipped |

CI (`.github/workflows/ci.yml`) was green on the last push to `main` (2026-10-03).

## What is on GitHub but not on `main`

Two PRs were opened while parking. Both merge cleanly onto 57a6f2b and onto each other, and
both pass their own suite; merging them is the maintainer's call.

- **PR #156, the dashboard redesign implementation.** PR #148 was stacked on #147's branch.
  #147 merged into `main` and fourteen seconds later #148 merged into its base branch instead,
  so its three commits never reached `main`. `main` still serves the pre-redesign page while
  `docs/superpowers/specs/2026-10-02-dashboard-redesign-design.md` describes the new one.
  #156 is that branch unchanged.
- **PR #155, one commit left on `tylervick/pocket-places`** after #143 merged, from that PR's
  review: a ladder can read "leads nowhere new", and a landing is keyed by the map it is on.

## Last measured results

All numbers below are quoted from the README section "Did Jev choose well?" as of 57a6f2b,
which is the fifth measured series; the PRs that wrote up each series are the only other
record. The raw data is local (see "Run data").

- Series 2 (PR #104): five branched runs from `route1.state` to the Boulder Badge, after the
  navigator fixes #88, #94, #100. Found that Jev never catches a second Pokémon (#110) and that
  every faint is therefore a blackout.
- Training arm (PR #111): training in the grass buys fewer blackouts and an easier Brock fight
  but does not recover its time by the badge (#103, closed).
- Series 4 (PR #119): after the shop and catch changes #112, #113, #114, #116, #117, #118.
- Series 5 (in the README now): five runs, 868 decisions, 33,640 branches. In the overworld,
  choosing the way Jev did saved game time against a random option and against always heading
  for the milestone, and was indistinguishable from the best alternative in hindsight. In
  battles, Jev was indistinguishable from the rules. Where Jev could have entered the Viridian
  Mart before the grass it never did, and the branches that did ended with a party of three or
  more far more often. Caveats in the README: decisions in a run are not independent, 6.5% of
  branches hit the frame cap, and Jev is not deterministic (probabilities vary by up to 0.16 on
  repeats), so each distinct question was answered once and cached.
- Move accuracy: 59%, not the 100% quoted early on (#68 has the re-scoring of the archived
  arms; the 100% came from the one arm that barely trained).

What has not been measured: anything past Brock. `--until beat_misty` was implemented and
tested against the ROM (PR #123, report in `docs/reports/2026-10-01-misty-implementation-report.md`)
and probed in twelve rounds of "frontier" runs (raw data under `.worktrees/probe/runs`, no
write-up), but there is no series readme for the road to Misty.

## Known gaps and open issues

Open issues on 2026-10-27, by area. Each carries a type label, an area label, and for
enhancements a stage label (`idea`, `shaped`, `spec`), so `gh issue list --label <area>` finds
them.

Bugs:

- #67: a run can hang in `BATTLE_WAIT`. #79 fixed the main cause (the No-PP move list); a rare
  residual stall is undiagnosed.

Brain (what Jev is asked):

- #52 (shaped): Jev is never told the bag is empty, so it walks past the shop into a gym fight.
  The supplies word that addressed it (#62, #63) was reverted (#66) because it livelocked at a
  Mart that cannot sell a Potion; #112, #118 and #122 narrowed the gap without closing it.
- #110: Jev rarely catches a second Pokémon. #112 to #120 produced the first catches (one run
  of eight in the last recorded batch); the measurement stands.
- #43, #58, #99: ideas for what else Jev could be told or asked (blackouts it has suffered,
  which move to trade for a fifth, what to focus on before choosing an option).

Executor:

- #8 (shaped): edge legs now name the map they land on (f6dfeb5); a `WARP_LAST_MAP` warp still
  cannot tell a blackout from a crossing.
- #138: with no balls and no money, the grass is still offered for the party-of-three goal.
- #34, #37, #22: the party-reorder macro, the offline livelock, ROM coverage for the
  post-switch turn.

Dashboard: #144, #145, #146, all filed by the redesign spec and waiting on PR #156.

Tooling: #13 (run logging at multi-hour scale), #68 (the accuracy headline), #92 (branch
measurement follow-ups), #83 (a Showdown battle-only mode), #74 and #97 (Cloudflare Access and
a milo.cat subdomain for the demo), #4 (Renovate's dependency dashboard).

Closed while parking: #86, the Pewter guard stall, which PR #89 fixed under its duplicate #88.

## Run data

Nothing under any `runs/` directory is on GitHub. It all lives on the machine that ran it, in
the git worktrees under `.worktrees/` of the main checkout, and it is kept as the raw data
behind the measured results above. Sizes on 2026-10-27:

| location | size | what it is |
| --- | --- | --- |
| `.worktrees/measure/runs` | 79 GB | `series2`, `series3`, `series4`, `series5`, `series5-pre122`, `batch16`: the branched series the README reports |
| `.worktrees/branching/runs` | 13 GB | the first branching measurement (PR #90, #82) and its `pool` |
| `.worktrees/probe/runs` | 6.7 GB | `frontier-v1` to `frontier-v12`, their `resume-*` continuations, `misty`: the past-Brock probes |
| `.worktrees/misty/runs` | 577 MB | runs behind PR #123 |
| `.worktrees/explore-q/runs` | 297 MB | runs behind PR #120 |
| `.worktrees/tried-expiry/runs` | 56 MB | runs behind PR #121 |
| `.worktrees/catch-move/runs` | 35 MB | runs behind PR #114 |
| `.worktrees/calibration-score/runs` | 15 MB | the calibration arms #68 re-scored |
| `.worktrees/past-brock/runs` | 16 MB | the probe in `docs/probes/past-brock.patch` |
| `.worktrees/party-b`, `party-size`, `grass-balls`, `mart-stock`, `arm-a` | 4 to 17 MB each | runs behind PRs #117, #113, #118, #112 and the `remeasure-pre4b` branch |
| `runs/` (main checkout) | 126 MB | `demo`, `demo-archive`, `handoff`, `shopcheck`, and tunnel and demo-loop logs |

Those worktrees were left in place for that reason; the save states in a worktree's `states/`
are also data, and two worktrees (`disabled`, `pocket-places`) hold states `main`'s
`Scripts/make-states.py` does not regenerate (`disabled.state`, `disabled_scratch.state`,
`mt_moon_b1f.state`).

## Preserved from uncommitted work

- `docs/probes/past-brock.patch`: a 22-line probe on `executor/goals.py` that added a
  `reach_cerulean` milestone with no route, to see whether generated options alone could carry a
  run east past the hand-written map graph. Its own comment says "not for merge"; it is kept
  because the frontier runs above were made with it. Apply with `git apply` onto 8a68251.
- `docs/reports/2026-10-01-misty-implementation-report.md`: the implementation report for the
  Misty work, written before it was pushed. It merged as PR #123.

## How to resume

1. `mise trust && mise install && mise run setup`, then `mise.local.toml` with `TYPESAFE_API_KEY`
   and `JEVPLAYS_ROM` (README, "Quick start"). `mise run states` writes the save states
   `tests/rom/` loads.
2. `mise run check` is lint plus tests and is what CI runs; expect the counts above.
3. Decide PR #155 and PR #156, and the Renovate PRs (#105 to #108, #149 to #154), which were
   left open on purpose.
4. `uv run jevplays run` for a full run from the intro, `jevplays run --state states/route1.state` to
   start past the intro; `mise run demo` for the always-on demo loop. The run data above is
   what `Scripts/branch-report.py` and `Scripts/accuracy.py` read.
5. GitHub Issues is the only backlog (`CLAUDE.md`, "Backlog"). The open issues above are
   labelled; nothing is in a TODO file.

The Orca workspace `production` is a detached checkout at b616b7f, the merge of PR #98, and
was left as it was.
