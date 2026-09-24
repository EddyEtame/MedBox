"""A browser that kept yesterday's crew.js showed yesterday's page after a
rebuild (24 Sep, seen in the built-in browser: crew.js served from cache
while the file on disk had changed). Pages and static files are revalidated
on every load; the API routes keep their own no-store."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server import app as station  # noqa: E402


class _Url:
    def __init__(self, path):
        self.path = path


class _Request:
    def __init__(self, path):
        self.url = _Url(path)


class _Response:
    def __init__(self, headers):
        self.headers = dict(headers)


def _through(path, headers):
    async def call_next(_request):
        return _Response(headers)
    return asyncio.run(station.revalidate_pages_and_scripts(_Request(path), call_next)).headers


def test_scripts_and_pages_are_revalidated_on_every_load():
    assert _through("/static/crew.js", {"content-type": "text/javascript"})["Cache-Control"] == "no-cache, must-revalidate"
    assert _through("/crew", {"content-type": "text/html; charset=utf-8"})["Cache-Control"] == "no-cache, must-revalidate"


def test_api_routes_keep_their_own_caching():
    out = _through("/api/status", {"content-type": "application/json", "Cache-Control": "no-store"})
    assert out["Cache-Control"] == "no-store"
    assert "Cache-Control" not in _through("/api/crew/week", {"content-type": "application/json"})
