# Windows convenience wrapper. All the logic lives in setup.py.
#   powershell -ExecutionPolicy Bypass -File setup.ps1
#   powershell -ExecutionPolicy Bypass -File setup.ps1 -y   (answer yes to prompts)

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

# setup.py needs 3.11 or newer, and THIS is where that has to be checked --
# not only there. The wrapper decides which interpreter setup.py runs under,
# so a probe that asks "does it start" hands over to the first thing on PATH
# that starts, and on a machine with several Pythons that is routinely the
# oldest one. It happened: `py -3` resolved to 3.9.13 while a working 3.11.9
# sat on PATH as `python`, and setup stopped at step 1 pointing at python.org
# for a Python that was already installed.
#
# An earlier version of this file did have a version probe and it was removed,
# because it ran under $ErrorActionPreference = "Stop" and python's banner on
# stderr became a terminating error. Removing "Stop" was the fix; removing the
# check was overshooting.
$PROBE = "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"

# In order. `py -3` first: it is the launcher's own answer for "the newest
# registered 3.x", so on a healthy machine it is right and costs one process.
# The explicit minors are for the machine where the newest REGISTERED one is
# too old and a newer Python is installed but is not the launcher's default.
# Then the bare names, which is how a python.org install with "Add to PATH"
# ticked is reachable when the launcher knows nothing about it.
$CANDIDATES = @(
    @{ name = "py";      prefix = @("-3")    },
    @{ name = "py";      prefix = @("-3.14") },
    @{ name = "py";      prefix = @("-3.13") },
    @{ name = "py";      prefix = @("-3.12") },
    @{ name = "py";      prefix = @("-3.11") },
    @{ name = "python";  prefix = @()        },
    @{ name = "python3"; prefix = @()        }
)

$exe = $null
$prefix = @()
# What each one turned out to be, so a failure can say so instead of telling
# somebody to install a Python they already have.
$seen = @()
$seenVersions = @()
# Things on PATH that carry the name and are not an interpreter at all: a dead
# py.exe left behind by an uninstall, a Store alias stub.
$dead = @()

# Each candidate is PROBED, not merely located. Get-Command only proves a file
# is on PATH, and on Windows that is not the same as proving it works:
#
#   - py.exe installs into C:\Windows for all users and is deliberately left
#     behind when a Python is uninstalled, so `py` can outlive every runtime it
#     could launch. `py -3` then exits 103 with one line on stderr.
#   - python.exe is frequently the Microsoft Store App Execution Alias, a stub
#     that exits non-zero and tries to open the Store.
#
# Both look exactly like a working interpreter to Get-Command.
#
# Note `2>&1` and NOT `2>$null`. Merging stderr into the output stream produces
# records that the assignment to $null swallows. Redirecting to $null is the
# construct that killed the earlier version of this file.
# EVERY match for a name is probed, not just the first. Get-Command returns one
# entry per matching executable on PATH, and %LOCALAPPDATA%\Microsoft\WindowsApps
# -- which holds the Store stubs -- is on the user PATH by default and often
# sits ahead of a python.org install. Taking only the first match would test
# the stub, watch it fail, and give up while the real interpreter sat second.
foreach ($cand in $CANDIDATES) {
    if ($exe) { break }
    foreach ($found in @(Get-Command $cand.name -CommandType Application -ErrorAction SilentlyContinue)) {
        if (-not $found.Source) { continue }
        $null = & $found.Source @($cand.prefix) -c $PROBE 2>&1
        if ($LASTEXITCODE -eq 0) {
            $exe = $found.Source
            $prefix = $cand.prefix
            break
        }
        # Too old, or not an interpreter at all. Ask what it is, for the
        # message below: telling somebody to install a Python while the one
        # they have sits unnamed on the next line is how this bug survived.
        #
        # Only an answer that looks like a version is worth printing. A dead
        # launcher asked for -3.14, -3.13, -3.12 and -3.11 in turn produces
        # four lines of "Python 3.14 not found!", which buries the one line
        # that matters under noise of its own making.
        $label = (@($found.Source) + $cand.prefix) -join ' '
        $answer = (& $found.Source @($cand.prefix) -c "import sys; print(sys.version.split()[0])" 2>&1 | Select-Object -First 1)
        if ("$answer" -match '^\d+\.\d+') {
            # Keyed on the VERSION, not the label. `py -3`, `py -3.12` and
            # `python` are routinely the same interpreter reached three ways,
            # and printing it three times reads as three problems.
            if ($seenVersions -notcontains "$answer") {
                $seenVersions += "$answer"
                $seen += "$label  ->  $answer"
            }
        } elseif ($dead -notcontains $found.Source) {
            $dead += $found.Source
        }
    }
}

if (-not $exe) {
    Write-Host "No Python 3.11 or newer on this machine." -ForegroundColor Red
    if ($seen.Count -or $dead.Count) {
        Write-Host ""
        Write-Host "What is here:" -ForegroundColor DarkGray
        foreach ($line in $seen) { Write-Host "  $line" -ForegroundColor DarkGray }
        foreach ($src in $dead) { Write-Host "  $src  ->  not a working interpreter" -ForegroundColor DarkGray }
        Write-Host ""
    }
    Write-Host "Install Python 3.11 or newer from https://www.python.org/downloads/"
    Write-Host "and tick 'Add python.exe to PATH' in the installer, then run this again."
    exit 1
}

# Say which interpreter won. On a machine with several Pythons the one that
# answered is not necessarily the one anybody expected, and a wheel with no
# build for that version then fails for a reason nothing else on screen
# explains.
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
