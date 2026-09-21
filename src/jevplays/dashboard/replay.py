"""Play a logged run back through the dashboard: the same decision events the loop sent, from
decisions.jsonl, with a delay between them. No emulator, no API key; the page cannot tell."""

import asyncio
import contextlib

from jevplays.dashboard.events import decision_event_from_dict, status_event
from jevplays.runlog import RunDir


async def replay(
    run_dir: RunDir,
    broadcaster,
    *,
    delay: float = 1.0,
    limit: int | None = None,
    wait_for_client: float = 0.0,
    sleep=asyncio.sleep,
) -> int:
    """Publish the logged decisions in order. With `wait_for_client` seconds, hold the first one
    until a tab connects (or that long passes) so a replay started before the browser is open
    does not play to an empty room."""
    decisions = list(run_dir.decisions())
    if limit is not None:
        decisions = decisions[:limit]
    total = len(decisions)
    if wait_for_client > 0:
        await broadcaster.publish(status_event("running", "waiting for a viewer"))
        # A timeout just means nobody came; play it out anyway.
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(broadcaster.first_client.wait(), timeout=wait_for_client)
    for i, d in enumerate(decisions, start=1):
        if i > 1 and delay > 0:
            await sleep(delay)
        await broadcaster.publish(status_event("running", f"replaying {run_dir.path.name}: {i}/{total}"))
        await broadcaster.publish(decision_event_from_dict(d))
    await broadcaster.publish(status_event("stopped", f"replayed {total} decisions"))
    return total
