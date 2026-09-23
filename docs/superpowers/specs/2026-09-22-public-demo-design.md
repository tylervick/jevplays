# A public link to the live demo

Issue #72. Amends `Scripts/demo-loop.py` (#71).

## The decision

#72 proposed moving the demo onto a Fly.io Machine, with `auto_stop_machines = "suspend"` as
the cost control. It stays on the machine it already runs on instead, shared through a tunnel as
an anyone-with-the-link URL. Why:

- **The ROM never leaves the machine.** No image, no registry, no cloud volume. That is stronger
  than #72's "never in the image" rule, and it holds without any build discipline.
- **Fly's scale-to-zero was the design's main unverified assumption.** It depends on Fly's proxy
  counting an open WebSocket as load, and on a suspend and resume not upsetting the stall
  watchdog's monotonic clock. A viewer-aware pause in our own code does the same job, and a unit
  test can pin it.

The demo is public: anyone with the URL can watch, with no login. Tyler will watch the TypeSafe
spend himself; the limits below keep it bounded.

## What runs

`mise run demo` (the supervisor), with a tunnel to its local port on the same machine. The
tunnel's setup is operational, not part of this repository, and nothing here depends on which
one it is.

## Limits

**Pause when unwatched.** This is the main cost control. `LoopConfig.pause_after`
(`--pause-after`):
- Past that many seconds with no WebSocket open, the loop publishes `unwatched`, stops stepping
  the game, and waits on `Broadcaster.wait_for_viewer()`.
- Crawlers and link previews fetch `/` without running the page's JS, so they never open the
  socket and never wake the game.
- The page closes its socket while the tab is hidden, so a forgotten background tab counts as
  nobody watching.
- The time spent paused moves the pacer's schedule forward, and it is not charged to the option
  in progress. Without that, every later step would look overdue, and the run would play flat
  out until it caught up: a burst of decisions the moment someone opens the link.

**Daily decision budget.** `--daily-decisions` on the supervisor, 1500 by default.
- The count comes from every run's `decisions.jsonl`, by each decision's own `ts`, per UTC day.
  A restarted supervisor reads the same number.
- Each run is started with `--max-decisions <what is left>`. At that number, the loop publishes
  `resting` and waits with the page still up.
- The supervisor replaces a resting run once the UTC day has turned over.
- The limit is carried by the run that spends it. Runs start in their own session and outlive a
  dead supervisor, so a cap enforced only by the supervisor would not survive it.
- Every decision counts, including ones code settles without asking Jev. That overcounts
  TypeSafe calls, which is the safe direction.

**Viewer cap.** `--max-viewers`, 20 by default.
- A socket past the cap is accepted, then closed with 1013. The page shows "the demo is full"
  and retries every 30 seconds.
- Each tab is its own frame stream from the home upload. The measured rate is ~175 KiB/s per
  viewer at 6x.
- The same measurement found capture scaling with `--speed`: 90 frames a second, ~720 KiB/s per
  viewer. `capture_every` now scales with speed. The rest of the gap to `fps` is #75.

**Watchdog.** `GET /health` answers `{"status", "viewers"}`. The supervisor treats `unwatched`
and `resting` as waiting on purpose: they are not stalls, and they reset the idle clock. The
loop's existing `paused` status still means stuck, and still counts towards a stall.

## runs/: logged and pruned, not `--no-log`

The stall watchdog (`progress()`) and the budget both read `decisions.jsonl`. With `--no-log`,
the watchdog would see 0 decisions forever and kill a healthy run every `--stall-after` seconds.
So logging stays on. Before each start, the supervisor deletes run directories last written more
than two days ago, keeping the newest whatever its age. That bounds `runs/demo/` at about two
days, and it keeps `Scripts/accuracy.py` working on recent demo runs.

## Not in this change

- Starting the demo and the tunnel again after a reboot: #73.
- A login in front of the link: #74.
- Capture tracking `fps` exactly: #75.
- Fly.io and a Dockerfile: dropped (see "The decision").
