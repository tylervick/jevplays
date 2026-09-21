"""Play a logged run back through the dashboard: the same decision events the loop sent, from
decisions.jsonl, with a delay between them. No emulator, no API key; the page cannot tell."""

import asyncio

from jevplays.dashboard.events import decision_event_from_dict, status_event
from jevplays.runlog import RunDir


async def replay(
    run_dir: RunDir,
    broadcaster,
    *,
    delay: float = 1.0,
    limit: int | None = None,
    sleep=asyncio.sleep,
) -> int:
    decisions = list(run_dir.decisions())
    if limit is not None:
        decisions = decisions[:limit]
    total = len(decisions)
    for i, d in enumerate(decisions, start=1):
        if i > 1 and delay > 0:
            await sleep(delay)
        await broadcaster.publish(status_event("running", f"replaying {run_dir.path.name}: {i}/{total}"))
        await broadcaster.publish(decision_event_from_dict(d))
    await broadcaster.publish(status_event("stopped", f"replayed {total} decisions"))
    return total
