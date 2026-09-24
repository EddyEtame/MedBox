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


def port_is_free(host: str, port: int) -> bool:
    """Whether a listening socket could take this address right now.

    uvicorn sets SO_REUSEADDR, and on Windows a bind with that option onto a
    port in use fails with WSAEACCES, "forbidden by its access permissions",
    rather than "address already in use". Measured here: 10013 with the option,
    10048 without. That is why the error never mentioned the port. So on
    Windows the probe is a plain bind, the strictest test there is. Elsewhere
    it sets the option as uvicorn does, so a station restarted a second after
    stopping, its old port still in TIME_WAIT, is not refused.
    """
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if not sys.platform.startswith("win"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(prog="medbox", description="MedBox station")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--check", action="store_true", help="verify install and exit")
    parser.add_argument("--reload", action="store_true", help="auto-reload while developing")
    parser.add_argument("--personal", type=int, default=6,
                        help="how many personal servers to start after the main one (0: none)")
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
    if not port_is_free(host, port):
        # Without this, uvicorn says "[WinError 10013] an attempt was made to
        # access a socket in a way forbidden by its access permissions", which
        # never mentions that something else has the port, and the address it
        # printed a line earlier opens whatever that something is. On the
        # machine this was written for, 8080 belongs to an auto-start Apache
        # that comes with EDB Postgres, and its page reads "Server is up and
        # running." Nobody would guess that is not MedBox.
        from server.config import python_command

        # Offer a port that is free now, not merely a different number.
        spare = next((p for p in range(port + 10, port + 200, 10) if port_is_free(host, p)), None)
        print(f"\n  Port {port} is already taken by another program on this machine,", file=sys.stderr)
        print("  so MedBox cannot listen there. Nothing is wrong with MedBox itself.\n", file=sys.stderr)
        if spare:
            print(f"  Start it on a free port:  {python_command('medbox.py')} --port {spare}", file=sys.stderr)
        print("  To change it for good, set `port` under [server] in config.toml.\n", file=sys.stderr)
        return 1
    print(f"\n  MedBox  ->  http://{host}:{port}")
    if args.reload or args.personal <= 0:
        print()
        uvicorn.run("server.app:app", host=host, port=port, reload=args.reload, log_level="info")
        return 0
    return serve_all(host, port, args.personal)


def serve_all(host: str, port: int, personal: int) -> int:
    """The main station, then one personal server per team member.

    Same process, same station, same database: each personal port serves the
    whole application behind its owner's page (server/personal.py), so a
    tablet on port 8771 is Eddy's, 8772 is Brad's, and the dashboard on the
    main port sees them all. The ports are chosen free, starting at port + 6.
    """
    import asyncio
    import os

    import uvicorn

    from server.sensors.synthetic import TEAM

    ids = [f"P-{i + 1:02d}" for i in range(min(personal, len(TEAM)))]
    chosen: list[tuple[str, int]] = []
    candidate = port + 6
    for pid in ids:
        while not port_is_free(host, candidate):
            candidate += 1
        chosen.append((pid, candidate))
        candidate += 1
    os.environ["MEDBOX_PERSONAL_PORTS"] = ",".join(f"{pid}:{p}" for pid, p in chosen)

    from server.app import app as station_app
    from server.personal import personal_app

    servers = [uvicorn.Server(uvicorn.Config(station_app, host=host, port=port, log_level="info"))]
    for pid, p in chosen:
        name = TEAM[int(pid[2:]) - 1][0]
        print(f"  {name:<9} ->  http://{host}:{p}")
        servers.append(uvicorn.Server(uvicorn.Config(personal_app(pid), host=host, port=p, log_level="warning")))
    print()

    async def run() -> None:
        tasks = [asyncio.create_task(s.serve()) for s in servers]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # One stopping (Ctrl+C lands on one of them) stops them all.
        for s in servers:
            s.should_exit = True
        await asyncio.gather(*pending, return_exceptions=True)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
