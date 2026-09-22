#!/usr/bin/env -S uv run --with playwright --script
"""Record the dashboard for a whole run, headless, and say where to cut it.

    mise exec -- uv run jevplays run --state states/route1.state --unpaced --port 8765 &
    Scripts/record-demo.py http://127.0.0.1:8765 /tmp/vid

Chromium records the page to a .webm at its own frame rate, so the result is a real recording
rather than a slideshow of screenshots. An *unpaced* run is the one to record: the loop still
streams the dashboard at `LoopConfig.fps`, so the whole run to the badge takes about twenty-five
seconds of wall clock instead of the hours real-time pacing would need.

Start this first and the run second -- it retries until the dashboard answers, so nothing of the
run is missed. It stops when the run's status turns `finished`, or when `--max` runs out; the
page flips to `disconnected` the moment the run's server exits, which is the real end of the
footage, and the last line printed says when that happened so the tail can be trimmed.

Then, with the printed LIVE and END seconds:

    ffmpeg -ss <LIVE> -t <END - LIVE> -i page.webm \
        -vf "scale=1280:-2:flags=lanczos,fps=25" \
        -c:v libx264 -preset slow -crf 27 -pix_fmt yuv420p -movflags +faststart -an demo.mp4

    ffmpeg -ss <a good moment> -t 8 -i page.webm \
        -vf "scale=900:-2:flags=lanczos,fps=15" \
        -c:v libwebp -q:v 50 -compression_level 6 -loop 0 -an demo.webp

WebP for the README because that is what renders inline; the MP4 is the full run. Never a GIF.
"""

import argparse
import asyncio
import time
from pathlib import Path

from playwright.async_api import async_playwright


async def record(url: str, out: Path, max_seconds: float, width: int, height: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": width, "height": height},
            record_video_dir=str(out),
            record_video_size={"width": width, "height": height},
        )
        page = await ctx.new_page()
        started = time.monotonic()
        live = None
        while time.monotonic() - started < max_seconds:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=2000)
                live = time.monotonic() - started
                break
            except Exception:
                await page.wait_for_timeout(300)
        if live is None:
            raise SystemExit(f"{url} never answered within {max_seconds:.0f}s")

        end = None
        while time.monotonic() - started < max_seconds:
            state = await page.evaluate("document.getElementById('status')?.dataset?.status || ''")
            if state in ("finished", "stopped"):
                end = time.monotonic() - started
                await page.wait_for_timeout(1500)  # a beat on the last frame
                break
            await page.wait_for_timeout(200)
        await ctx.close()
        await browser.close()

    print(f"LIVE {live:.1f}")
    print(f"END {end:.1f}" if end else f"END {max_seconds:.1f} (never finished)")
    for f in sorted(out.glob("*.webm")):
        print(f"VIDEO {f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("url")
    ap.add_argument("out", type=Path)
    ap.add_argument("--max", type=float, default=300.0, help="give up after this many seconds")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=820)
    args = ap.parse_args()
    asyncio.run(record(args.url, args.out, args.max, args.width, args.height))


if __name__ == "__main__":
    main()
