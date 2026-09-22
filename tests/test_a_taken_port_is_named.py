"""A port somebody else holds is reported as exactly that.

On the machine this project moved to, 8080 belongs to an auto-start Apache
that comes with EDB Postgres. Setup finished with "Then open
http://127.0.0.1:8080", which opened a page reading "Server is up and
running." The station itself printed its own address, then "[WinError 10013]
an attempt was made to access a socket in a way forbidden by its access
permissions", and then hung at "Waiting for application shutdown" instead of
exiting. Three messages, and none of them said the port was taken.
"""
from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _setup():
    spec = importlib.util.spec_from_file_location("medbox_setup", ROOT / "setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _occupy() -> socket.socket:
    """Listen on a free port the way another program would."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen()
    return s


def test_the_station_says_the_port_is_taken_and_exits():
    holder = _occupy()
    port = holder.getsockname()[1]
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "medbox.py"), "--port", str(port)],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT),
        )
    finally:
        holder.close()
    said = r.stdout + r.stderr
    assert r.returncode != 0, "it reported success on a port it could not have"
    assert f"Port {port} is already taken" in said, said[-600:]
    assert "--port" in said, "it names no way out"


def test_setup_reads_the_port_the_station_will_use():
    from server.config import CONFIG

    assert _setup().read_port() == CONFIG.server.port


def test_setup_warns_when_the_port_is_taken(monkeypatch, capsys):
    s = _setup()
    holder = _occupy()
    monkeypatch.setattr(s, "read_port", lambda: holder.getsockname()[1])
    try:
        s.check_port()
    finally:
        holder.close()
    assert any("taken" in w for w in s.warnings), capsys.readouterr().out


def test_setup_is_quiet_when_the_port_is_free(monkeypatch):
    s = _setup()
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    free = probe.getsockname()[1]
    probe.close()
    monkeypatch.setattr(s, "read_port", lambda: free)
    s.check_port()
    assert not s.warnings, s.warnings
