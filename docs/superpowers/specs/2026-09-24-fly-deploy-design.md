# The demo on Fly.io

Amends `docs/superpowers/specs/2026-09-22-public-demo-design.md` (#72, #76) and
`Scripts/demo-loop.py`.

## The decision

The public demo moves off the Mac mini onto one Fly.io Machine, deployed from `main` on every
merge, with alerts to Tyler's ntfy. It replaces the public-demo spec's decision that the demo
stays on the machine it runs on. What changed:

- **The goal changed.** The demo is meant to be a service, not a process on a desk: a stable URL,
  deploys nobody runs by hand, and logs and alerts reachable from anywhere. A reboot, a sleep, or a
  measurement hogging the CPU should not take it down.
- **Fly's unverified assumption no longer matters.** The public-demo spec rejected Fly partly
  because its cost control was `auto_stop_machines`, which depended on Fly's proxy counting an open
  WebSocket as load. The pause-when-unwatched that spec added instead lives in our own code and
  works the same on any host. Auto-stop stays off.
- **Its other reason, "the ROM never leaves the machine," is traded for "the ROM never enters an
  image."** The ROM goes on a Fly volume that only this app mounts. That is still not committing
  it: it is never in git, never in an image, never in a registry.

The hosting choice was checked against current pricing and docs on 2026-09-23. Fly was the only
managed platform with a persistent volume reachable over sftp, WebSockets with no idle timeout,
cheap egress ($0.02/GB), and a GitHub Actions deploy. A plain VPS behind a tunnel was cheaper but
would have left deploys, restarts, logs and alerting to us. Railway (deploy-time-only health
checks, 5 GB volume cap), Render ($0.15/GB egress), Koyeb (volumes in preview) and Cloud Run
(60-minute WebSocket cap, no block volume) each failed on one requirement.

## Sizing

Measured on the Mac mini (M1), one viewer attached, `--speed 3`, `--no-brain`: 4-5% of one core,
about 75 MB resident, 15 frames/s at 113 KiB/s. Calling TypeSafe adds network waits, not CPU.

Fly's `shared-cpu-1x` guarantees 6.25% of a core and banks burst credit while under it. A Fly
shared vCPU is slower than an M1 core, so the demo may sit above that baseline while watched,
and earns credit back while paused. Start on `shared-cpu-1x` with 1 GB. Once deployed, watch a
20-minute viewing session (`fly machine status`, and whether frames stay at 15/s). If it
throttles, move to `shared-cpu-2x`, and record the size and the reason in this spec.

## What runs

**Image.** A `Dockerfile` installs the package from `uv.lock` on the `.python-version` Python,
headless (PyBoy already runs with `window="null"`). It copies `src/`, `Scripts/demo-loop.py`,
`pyproject.toml` and `uv.lock`, and nothing else. `.dockerignore` excludes `roms/`, `states/`,
`runs/`, `*.gb`, `*.gbc`, `*.state`, `*.ram` and `mise.local.toml` as well, so a build from a
dirty checkout cannot pick them up either.

**Machine.** `fly.toml`: app `jevplays` (or whatever `fly launch` assigns; the file records it),
one region, one `shared-cpu-1x` Machine with 1 GB, `auto_stop_machines = "off"`, internal port
8765, and an HTTP check on `GET /health`.

**Volume.** 1 GB mounted at `/data`:
- `/data/rom/pokemon-red.gb`: uploaded once by Tyler with `fly ssh sftp put`.
- `/data/runs/`: the supervisor's `--runs-dir`, pruned to two days as now (~50 MB/day).

No save states: the demo starts from the intro (#80).

**Process.** The Machine runs `Scripts/demo-loop.py --host 0.0.0.0 --runs-dir /data/runs` with
`JEVPLAYS_ROM=/data/rom/pokemon-red.gb`, and the speed and daily budget the Mac mini uses today
(`--speed 3 --daily-decisions 3000`). If the ROM file is missing, the supervisor exits with a
message naming the `fly ssh sftp put` command, instead of starting runs that die at once.

**Secrets**, in `fly secrets`, never in the repo: `TYPESAFE_API_KEY`, `NTFY_URL` (server and
topic; on ntfy a topic name works like a password) and `NTFY_TOKEN` if the server requires one.

## Supervisor changes

`Scripts/demo-loop.py` was written to be started by hand in a terminal. Unattended on Fly it needs
three things.

**A deploy does not lose the run.** Fly stops a Machine with SIGTERM before a deploy or a stop.
- The supervisor handles SIGTERM by forwarding it to the run's process group, waiting for it to
  exit (the run already writes an exit checkpoint on SIGTERM), then exiting 0.
- A run records `finished_at` in `run.json` when it finishes at the badge.
- When the supervisor starts, if the newest run under `--runs-dir` has no `finished_at` and has a
  checkpoint, its first run is `jevplays run --resume <dir>` instead of a new one, with the same
  budget arithmetic (`--max-decisions` counts the decisions this process makes, and the day's
  total is still read from every `decisions.jsonl`). Only the first run of a supervisor's life resumes. A run the supervisor
  itself killed as stalled, or one that died, is replaced by a fresh run as now: resuming a hang
  from the checkpoint before it would likely hang again.

**A wedged demo gets restarted by Fly.** A failing health check on Fly takes the Machine out of
routing but does not restart it; Fly restarts a Machine only when its main process exits. Today
the supervisor backs off forever on a run that keeps failing to start. Instead, after 5
consecutive runs that each lasted under 30 seconds, it exits non-zero, and Fly's restart policy
starts the Machine again.

**It says what happened.** A `notify(message)` posts to `NTFY_URL` (with `NTFY_TOKEN` as a bearer
token when set). Without `NTFY_URL` it does nothing, so `mise run demo` on a laptop behaves exactly
as now. A failed post is printed and otherwise ignored: an alert must never stop the demo. It
posts once per event, not once per poll:
- the supervisor started (after a deploy or a restart), and whether it resumed a run;
- a run was killed as stalled;
- the supervisor is exiting on a crash loop;
- the daily budget ran out (a run went `resting`), and when a new day's run starts.

## Deploys

`.github/workflows/deploy.yml`:
- Runs on push to `main`, and only after the `ci` workflow's tests pass for that commit
  (`workflow_run` on `ci` completing successfully on `main`).
- Uses `superfly/flyctl-actions/setup-flyctl`, SHA-pinned like every other action here, and runs
  `flyctl deploy --remote-only`, so the image is built on Fly's builder from the checkout. A clean
  checkout contains no game data, so neither does the image.
- `FLY_API_TOKEN` is a deploy token scoped to this one app, stored as a GitHub secret.
- Posts the result, success or failure with the commit, to ntfy (`NTFY_URL`/`NTFY_TOKEN` as
  GitHub secrets too).
- It has no ROM and never touches the volume.

A deploy replaces the Machine in place, so the page is down for about a minute and reconnects by
itself; the run resumes from its exit checkpoint.

## Uptime check

The supervisor cannot report its own Machine being down, so `.github/workflows/uptime.yml` does:
- Runs every 10 minutes on a schedule. GitHub runs scheduled workflows late at times, so an
  outage can take 10-30 minutes to be noticed. Accepted for a demo.
- Fetches `https://<app>.fly.dev/health` with a short timeout. Any non-2xx response or a failed
  request is down. Every `status` value counts as up, including `unwatched` and `resting`: those
  mean the process is answering.
- Posts to ntfy only when the answer differs from the previous scheduled run's conclusion (down
  once, recovered once), read with `gh run list` for this workflow. The job fails while the demo
  is down, so the workflow's own history is the state.

## Rollout

Tyler does the account steps: `fly launch --no-deploy` against the committed `fly.toml`,
`fly volumes create`, `fly ssh sftp put` the ROM, `fly secrets set`, the GitHub secrets, and the
first deploy. Then:

1. Check the page, `/health`, a deploy that resumes a run, and an ntfy post for each event.
2. Measure CPU as in "Sizing"; resize if needed.
3. Stop the Mac mini's supervisor and tunnel. Close #73 as superseded.

The README gains a "Production" section: the one-time setup, how a deploy happens, `fly logs`,
and what each ntfy message means. It says nothing about how the Mac mini's tunnel works.

## Risks

- **Brief outages.** Each deploy and each restart is about a minute of reconnecting.
- **One host.** A Fly volume lives on one host's drive; if that host dies, so does the demo until
  the app is moved to a new volume. The recovery is `fly volumes create` and re-uploading the ROM;
  `runs/` is disposable, and Fly keeps daily volume snapshots for 5 days.
- **A public URL.** The repo is public and `fly.toml` names the app, so the `fly.dev` URL is
  known. It was going to be shared anyway; the page is read-only, and the budget, pause and viewer
  cap still bound what it costs.

## Not in this change

- A custom domain on `milo.cat` (DNS only, no Cloudflare proxy): #97.
- A login in front of the page: #74.
- More than one Machine or region: the emulator is one process holding one game.
