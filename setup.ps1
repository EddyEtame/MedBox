# Windows convenience wrapper. All the logic lives in setup.py.
#   powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Find-Python {
    foreach ($cmd in @("python", "python3", "py")) {
        $exe = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $exe) { continue }
        $args = if ($cmd -eq "py") { @("-3", "-c") } else { @("-c") }
        $probe = "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)"
        & $exe.Source @args $probe 2>$null
        if ($LASTEXITCODE -eq 0) {
            return @{ Exe = $exe.Source; Prefix = $(if ($cmd -eq "py") { @("-3") } else { @() }) }
        }
    }
    return $null
}

$py = Find-Python
if ($null -eq $py) {
    Write-Host "No Python 3.11+ found." -ForegroundColor Red
    Write-Host "Install it from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'."
    exit 1
}

& $py.Exe @($py.Prefix + @("setup.py") + $args)
exit $LASTEXITCODE
