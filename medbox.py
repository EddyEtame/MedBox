#!/usr/bin/env python3
"""MedBox entry point.

    python medbox.py                 start the station
    python medbox.py --port 9000     on a different port
    python medbox.py --check         verify the install and exit

One command, one port, no internet.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    parser = argparse.ArgumentParser(prog="medbox", description="MedBox station")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--check", action="store_true", help="verify install and exit")
    parser.add_argument("--reload", action="store_true", help="auto-reload while developing")
    args = parser.parse_args()

    try:
        import uvicorn
        from server.config import CONFIG
    except ImportError as exc:
        print(f"Dependencies are missing ({exc}).", file=sys.stderr)
        print("Run:  python setup.py", file=sys.stderr)
        return 1

    if args.check:
        from server import scenarios
        from server.triage import assess

        demo = assess(temperature=39.2, spo2=92, pulse=118, respiration=23)
        print(f"MedBox install OK")
        print(f"  triage engine   NEWS2 -> {demo.total} ({demo.urgency.value})")
        print(f"  scenarios       {', '.join(scenarios.available()) or 'none found'}")
        print(f"  database        {CONFIG.database.resolved}")
        print(f"  ai model        {CONFIG.ai.model} (started separately by Ollama)")
        return 0

    host = args.host or CONFIG.server.host
    port = args.port or CONFIG.server.port
    print(f"\n  MedBox  ->  http://{host}:{port}\n")
    uvicorn.run(
        "server.app:app",
        host=host,
        port=port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
