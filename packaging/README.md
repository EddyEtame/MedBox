# MedBox portable Windows bundle

`tools/build-portable.ps1` creates a folder that can be copied to an NTFS USB
drive and started with `MedBox.exe`. The destination is always explicit. The
builder never overwrites it, and only removes its own uniquely named staging
folders after first checking their parent and prefix.

## Inputs

The build is offline by default. Prepare these inputs on a drive with enough
space (the current machine should use `D:`):

- a Python 3.11 x64 embeddable ZIP from python.org, plus its published SHA-256;
- a wheelhouse containing every wheel from `requirements.txt` and, when voice
  is included, `requirements-speech.txt`;
- Ollama, its configured model store, and the Faster Whisper model if present.

The builder auto-detects the installed Ollama runtime and `%USERPROFILE%\.ollama\models`.
It copies only `ollama.exe`, the CPU runner DLLs, and the blobs referenced by
the configured model manifest. GPU runtimes and unrelated or partial model
blobs are deliberately excluded.

The exact Python URL and official SHA-256 are pinned in `assets.lock.json`.

Environment variables may replace long command arguments:

- `MEDBOX_PYTHON_RUNTIME`
- `MEDBOX_WHEELHOUSE`
- `MEDBOX_OLLAMA_RUNTIME`
- `MEDBOX_OLLAMA_MODELS`
- `MEDBOX_SPEECH_MODEL`

## Commands

Preflight does not create the destination:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\build-portable.ps1 `
  -Mode Preflight -Destination D:\MedBox-Wednesday `
  -PythonRuntime D:\MedBox-assets\python-3.11.9-embeddable-amd64.zip `
  -PythonSha256 33b448f95fecb7c6f802157dbd5e6b40a2ad9bfc8b95ca634a06ba4073ad1ac0 `
  -Wheelhouse D:\MedBox-assets\wheels
```

Build uses a new destination folder. It refuses to replace an existing one:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\build-portable.ps1 `
  -Mode Build -Destination D:\MedBox-Wednesday `
  -PythonRuntime D:\MedBox-assets\python-3.11.9-embeddable-amd64.zip `
  -PythonSha256 33b448f95fecb7c6f802157dbd5e6b40a2ad9bfc8b95ca634a06ba4073ad1ac0 `
  -Wheelhouse D:\MedBox-assets\wheels `
  -RequireComplete
```

Verify a copied bundle without starting it:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\build-portable.ps1 `
  -Mode Check -Destination D:\MedBox-Wednesday
```

Run the checksum verification plus the bundled Python/Ollama smoke checks:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\build-portable.ps1 `
  -Mode Smoke -Destination D:\MedBox-Wednesday
```

`-AllowNetwork` is an explicit escape hatch for pip and .NET restore. It is
never enabled implicitly. Temporary files, pip cache, NuGet cache, .NET build
output, and staging all stay beside the destination, not on the system drive.

## Result layout

```text
MedBox.exe
LISEZ-MOI.txt           instructions operateur en francais
tools/                  assistant.ps1 (kill and relaunch the assistant on stage), preflight.ps1
app/                    Python application and optional speech model
runtime/python/         Python runtime and pinned dependencies
runtime/ollama/         CPU-only Ollama runtime when available
models/ollama/          only the configured model closure
documentation/          operator/project documentation
licenses/               notices and available license material
manifests/              component metadata and SHA256SUMS
data/                    mutable local database and session state
logs/                    mutable process logs
```

The repository root carries `LICENSE` (Apache-2.0) and the builder copies it
into `licenses/`. If it ever went missing, the builder would record that as
`licenses/PROJECT-LICENSE-MISSING.txt`: a warning, not permission to
redistribute the bundle.

## What was learned launching it cold

Measured on the build machine, 23 September 2026, from a path with a space,
with `PATH` reduced to `C:\Windows`, no Python and no Ollama reachable:

- The embeddable Python, with `import site` enabled in its `._pth`, still
  puts the current user's roaming `site-packages` on `sys.path`. A bundle
  that resolves one import there works on the laptop that built it and on no
  other. The launcher starts the runtime with `-s` and `PYTHONNOUSERSITE=1`,
  and the builder's smoke test runs it the same way and refuses a runtime
  that still sees the host.
- Build on the internal SSD and copy to the USB stick afterwards. Hashing
  1.5 GB on a USB stick took seven minutes per pass; on the SSD the whole
  build takes five.
- The .NET SDK leaves compiler servers running after `publish`, and on a fast
  disk they still hold files in the work folder when cleanup runs. The
  builder shuts them down and no longer reports a finished bundle as failed
  because a temporary file was locked.
- An `ollama.exe` started with elevated rights (the installer leaves one
  behind until the next reboot) cannot be stopped from a normal window.
  `tools\assistant.ps1 stop` names it instead of printing a stack, judges the
  kill by what the station itself reports, and `preflight.ps1` refuses to say
  "Pret" while one exists. The bundle's own Ollama is a normal child process
  and dies on the first try.
- `tools\assistant.ps1 start -Bundle <folder>` relaunches the bundle's own
  Ollama on port 11555. That process is not a child of `MedBox.exe`: closing
  the launcher leaves it running, and `stop` is what ends it.
