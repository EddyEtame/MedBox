"""The one design decision, checked the way Python actually resolves imports.

"Nothing in server/triage.py, server/sensors/ or server/db.py may import from
server/ai/. There is a test." There was one, and it searched triage.py's text
for "import ai" and "from .ai". It stayed green for `from server.ai import
schemas`, for `import server.ai.validate`, for `from . import ai`, and for any
of them in sensors/ or db.py, which it never opened. Shown by planting each
one in a scratch copy and running it.

So this parses every module on the fast track and resolves every import,
relative or absolute, to the module it names. It is the answer to the first
question a jury asks, so it has to be one that cannot be walked around.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Everything README.md marks [FAST]. The rule in CLAUDE.md names triage,
# sensors and db; quarantine and bus are on the same path, so they count too.
FAST = sorted(
    [ROOT / "server" / n for n in ("triage.py", "quarantine.py", "bus.py", "db.py")]
    + list((ROOT / "server" / "sensors").glob("*.py"))
)


def _package(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts[:-1])


def _imports(source: str, package: str) -> list[str]:
    """Every module an import in this source can bind, fully resolved."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                module = ".".join(base + ([node.module] if node.module else []))
            else:
                module = node.module or ""
            found.append(module)
            # `from server import ai` and `from . import ai` bind the package
            # through a name, not through the module path.
            found += [f"{module}.{a.name}" for a in node.names]
    return found


def _ai(modules: list[str]) -> list[str]:
    return [m for m in modules if m == "server.ai" or m.startswith("server.ai.")]


@pytest.mark.parametrize("path", FAST, ids=lambda p: str(p.relative_to(ROOT)))
def test_the_fast_track_does_not_import_the_ai(path: Path):
    bad = _ai(_imports(path.read_text(encoding="utf-8"), _package(path)))
    assert not bad, (
        f"{path.relative_to(ROOT)} imports {bad}. The measurement path must "
        "not depend on the AI in any form; if it needs to, the design has "
        "drifted. Stop and fix that instead."
    )


@pytest.mark.parametrize("form", [
    "from server.ai import schemas",
    "import server.ai.validate",
    "from ..ai import ollama",
    "from .. import ai",
    "from server import ai",
])
def test_the_guard_sees_every_form_the_old_one_missed(form: str):
    """Parsed as if written in a module under server/sensors/."""
    assert _ai(_imports(form, "server.sensors")), f"the guard does not see: {form}"
