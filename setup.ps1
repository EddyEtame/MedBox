# Windows convenience wrapper. All the logic lives in setup.py.
#   powershell -ExecutionPolicy Bypass -File setup.ps1

# -LiteralPath, not -Path: -Path treats [ and ] as wildcard metacharacters, so
# a clone under a folder like "MedBox [old]" fails to resolve. A space is fine
# either way. If this does not land, "setup.py" below would resolve against
# whatever directory the shell happened to be in.
Set-Location -LiteralPath $PSScriptRoot
if ((Get-Location).Path -ne $PSScriptRoot) {
    Write-Host "Could not move to $PSScriptRoot" -ForegroundColor Red
    exit 1
}

# Deliberately NOT "Stop".
#
# Windows PowerShell 5.1 turns anything a native program writes to stderr into
# an error record, and under "Stop" that error is terminating. Python writes
# its banner, its warnings and its deprecation notices to stderr, none of which
# are failures. An earlier version of this file set "Stop" and then ran python
# to probe its version; python printed its banner, PowerShell called that a
# NativeCommandError, and setup died before it ever created the virtual
# environment. Everything after it then failed for the obvious downstream
# reason, which made it look like four problems instead of one.
$ErrorActionPreference = "Continue"

# There is no version check here. setup.py checks the version itself and
# reports it in plain words, so all this wrapper has to do is find an
# interpreter that runs at all and hand over. The old probe also assigned to
# $args, which is an AUTOMATIC variable holding the caller's own arguments.
$exe = $null
$prefix = @()

# Each candidate is PROBED, not merely located. Get-Command only proves a file
# is on PATH, and on Windows that is not the same as proving it works:
#
#   - py.exe installs into C:\Windows for all users and is deliberately left
#     behind when a Python is uninstalled, so `py` can outlive every runtime it
#     could launch. `py -3` then exits 103 with one line on stderr.
#   - python.exe is frequently the Microsoft Store App Execution Alias, a stub
#     that exits non-zero and tries to open the Store.
#
# Both look exactly like a working interpreter to Get-Command, so trusting it
# would commit to a dead launcher and never try the python that does work.
# Running `-c "pass"` is the cheap way to tell them apart: it prints nothing,
# writes nothing to stderr, and exits 0 on a real Python.
#
# Note `2>&1` and NOT `2>$null`. Merging stderr into the output stream produces
# records that the assignment to $null swallows. Redirecting to $null is the
# construct that killed the earlier version of this file.
# EVERY match is probed, not just the first. Get-Command returns one entry per
# matching executable on PATH, and %LOCALAPPDATA%\Microsoft\WindowsApps -- which
# holds the Store stubs -- is on the user PATH by default and often sits ahead
# of a python.org install. Taking only the first match would test the stub,
# watch it fail, and give up while the real interpreter sat second in the list.
foreach ($found in @(Get-Command "py" -CommandType Application -ErrorAction SilentlyContinue)) {
    if (-not $found.Source) { continue }
    $null = & $found.Source -3 -c "pass" 2>&1
    if ($LASTEXITCODE -eq 0) {
        $exe = $found.Source
        $prefix = @("-3")
        break
    }
}

if (-not $exe) {
    foreach ($name in @("python", "python3")) {
        foreach ($found in @(Get-Command $name -CommandType Application -ErrorAction SilentlyContinue)) {
            if (-not $found.Source) { continue }
            $null = & $found.Source -c "pass" 2>&1
            if ($LASTEXITCODE -eq 0) {
                $exe = $found.Source
                # Reset, in case the py launcher was found but failed its
                # probe. Leaving @("-3") here would run `python -3 setup.py`,
                # which python rejects outright.
                $prefix = @()
                break
            }
        }
        if ($exe) { break }
    }
}

if (-not $exe) {
    Write-Host "No working Python found on this machine." -ForegroundColor Red
    Write-Host "Install Python 3.11 or newer from https://www.python.org/downloads/"
    Write-Host "and tick 'Add python.exe to PATH' in the installer, then run this again."
    exit 1
}

# Say which interpreter won. `py -3` resolves to the HIGHEST registered 3.x,
# which on a machine with several Pythons is not necessarily the one anything
# was tested against, and a wheel with no build for that version then fails for
# a reason nothing else on screen explains.
Write-Host "Using: $exe $($prefix -join ' ')" -ForegroundColor DarkGray

# Cleared first. $LASTEXITCODE is session state, not per-statement state: if
# the call below never launches a process, the previous value survives, and a
# stale 0 would report a setup that never happened as a success. Running the
# script directly in an existing session is enough for that to matter.
$global:LASTEXITCODE = $null
& $exe @prefix "setup.py" @args

# $LASTEXITCODE is only set once a native program has actually run and
# returned. If the call never got that far, it is whatever it was before, or
# $null on a fresh session -- and "exit $null" exits 0, which would report a
# setup that never happened as a success.
if ($null -eq $LASTEXITCODE) { exit 1 }
exit $LASTEXITCODE
