"""Static and safe-path checks for the Windows portable bundle builder."""
from __future__ import annotations

import shutil
import subprocess
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "tools" / "build-portable.ps1"


def powershell() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def test_builder_and_packaging_notices_exist():
    assert SCRIPT.is_file()
    assert (ROOT / "packaging" / "README.md").is_file()
    assert (ROOT / "packaging" / "THIRD-PARTY-NOTICES.txt").is_file()
    assert (ROOT / "packaging" / "LISEZ-MOI.txt").is_file()
    # One double-click for the presenter (24 Sep): the check, then the launch.
    button = (ROOT / "packaging" / "DEMARRER-LA-DEMO.cmd").read_text(encoding="ascii")
    assert "preflight.ps1" in button and "MedBox.exe" in button and "if errorlevel 1" in button
    assert "DEMARRER-LA-DEMO.cmd" in (ROOT / "tools" / "build-portable.ps1").read_text(encoding="ascii")
    lock = json.loads((ROOT / "packaging" / "assets.lock.json").read_text())
    assert lock["python"]["sha256"] == "33b448f95fecb7c6f802157dbd5e6b40a2ad9bfc8b95ca634a06ba4073ad1ac0"


def test_builder_requires_an_explicit_destination_and_never_replaces_it():
    body = SCRIPT.read_text(encoding="utf-8")
    assert "[Parameter(Mandatory = $true)]" in body
    assert "Destination already exists" in body
    assert "Move-Item -LiteralPath $stage -Destination $Destination" in body
    assert "Remove-Item -LiteralPath $Destination" not in body
    assert "Assert-SafeEphemeral" in body


def test_builder_keeps_caches_with_the_destination_work_folder():
    body = SCRIPT.read_text(encoding="utf-8")
    assert '$env:TEMP = $Work' in body
    assert '$env:TMP = $Work' in body
    assert '$env:PIP_CACHE_DIR = $cache' in body
    assert '$env:NUGET_PACKAGES = $nuget' in body


def test_builder_is_ascii_for_windows_powershell_51():
    SCRIPT.read_bytes().decode("ascii")


def test_builder_copies_only_the_configured_ollama_closure():
    body = SCRIPT.read_text(encoding="utf-8")
    assert "Get-OllamaModelClosure" in body
    assert "Get-FileHash -LiteralPath $blobPath -Algorithm SHA256" in body
    assert 'Get-ChildItem -LiteralPath $cpuLibSource -File -Filter "*.dll"' in body
    assert "partial" not in "\n".join(
        line for line in body.splitlines() if "Copy-Item" in line and "blob" not in line.lower()
    )


@pytest.mark.skipif(powershell() is None, reason="PowerShell is unavailable")
def test_builder_parses_in_powershell():
    shell = powershell()
    probe = (
        "$errors = $null; $tokens = $null; "
        "$null = [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{SCRIPT}', [ref]$tokens, [ref]$errors); "
        "if ($errors.Count) { $errors | % { $_.Message }; exit 1 }; 'ok'"
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-Command", probe],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(powershell() is None, reason="PowerShell is unavailable")
def test_drive_root_is_rejected_before_any_write(tmp_path):
    # Path.GetPathRoot('/') is '/' under pwsh on non-Windows; on Windows use C:\.
    root = Path(tmp_path.anchor)
    result = subprocess.run(
        [
            powershell(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-Mode",
            "Preflight",
            "-Destination",
            str(root),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "never a drive root" in (result.stdout + result.stderr)


@pytest.mark.skipif(powershell() is None, reason="PowerShell is unavailable")
def test_check_mode_detects_payload_tampering(tmp_path):
    bundle = tmp_path / "bundle"
    files = {
        "MedBox.exe": b"MZ-test",
        "app/medbox.py": b"print('test')\n",
        "runtime/python/python.exe": b"MZ-python-test",
        "manifests/bundle-manifest.json": json.dumps(
            {"readiness": {"completeForVoiceDemo": True}}
        ).encode(),
    }
    for relative, data in files.items():
        target = bundle / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    sums = []
    for relative, data in sorted(files.items()):
        sums.append(f"{hashlib.sha256(data).hexdigest()} *{relative}")
    (bundle / "manifests" / "SHA256SUMS").write_text(
        "\n".join(sums) + "\n", encoding="ascii"
    )

    command = [
        powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(SCRIPT),
        "-Mode",
        "Check",
        "-Destination",
        str(bundle),
    ]
    valid = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert valid.returncode == 0, valid.stdout + valid.stderr
    (bundle / "app" / "medbox.py").write_text("tampered\n", encoding="ascii")
    tampered = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert tampered.returncode != 0
    assert "Checksum mismatch" in (tampered.stdout + tampered.stderr)
