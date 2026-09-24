# Kill the assistant on stage, and bring it back, on Windows.
#   powershell -ExecutionPolicy Bypass -File tools\assistant.ps1 stop
#   powershell -ExecutionPolicy Bypass -File tools\assistant.ps1 start
#   powershell -ExecutionPolicy Bypass -File tools\assistant.ps1 start -Bundle D:\MedBox-Portable
#
# Why this exists: on Windows, Ollama is two processes. "ollama app.exe" sits in
# the tray and "ollama.exe" is the server it supervises. End the server alone -
# Task Manager, taskkill, Stop-Process - and the tray app starts a new one.
# Measured on the demo machine: a new server was answering five seconds later,
# and the station showed the assistant as back while the presenter was still
# saying it was gone. So the tray app goes first, then the server.
#
# Two more things learned on the same machine:
# - An ollama.exe left behind by the installer runs with elevated rights until
#   the next reboot, and a normal window cannot stop it. Stop-Process prints a
#   red stack and the assistant keeps answering. This script names the PID
#   instead, and preflight.ps1 refuses to say "Pret" while one exists.
# - The portable bundle starts its own ollama.exe on port 11555, never 11434.
#   "stop" kills every ollama it can reach and checks both ports; "start
#   -Bundle <folder>" relaunches the bundle's own server, "start" alone the
#   installed one.
#
# Pure ASCII on purpose: a BOM-less .ps1 is decoded with the system code page.

param([string]$Action = "", [string]$Bundle = "", [int]$StationPort = 8765)

# Not "Stop": see setup.ps1 for what that does to native programs' stderr.
$ErrorActionPreference = "Continue"

$APP = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
$INSTALLED_PORT = 11434
$BUNDLE_PORT = 11555

# A raw TCP connect, not Invoke-WebRequest: the first web request in a fresh
# PowerShell 5.1 spends seconds on proxy auto-detection, and the first version
# of this script took twenty seconds to say "stopped" in front of an audience.
function Test-Answering([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        return $client.ConnectAsync("127.0.0.1", $Port).Wait(1000)
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Get-AnsweringPorts {
    return @(@($INSTALLED_PORT, $BUNDLE_PORT) | Where-Object { Test-Answering $_ })
}

# The station itself is the judge: it probes its own assistant every five
# seconds and /api/status says what it currently believes. That is what the
# audience sees, whichever Ollama and whichever port it was configured with.
# HttpWebRequest with no proxy, for the same reason as the raw connect above.
function Get-StationView([int]$Port) {
    try {
        $req = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:$Port/api/status")
        $req.Proxy = $null
        $req.Timeout = 2000
        $resp = $req.GetResponse()
        $reader = New-Object IO.StreamReader($resp.GetResponseStream())
        $body = $reader.ReadToEnd()
        $reader.Close(); $resp.Close()
        $status = $body | ConvertFrom-Json
        if ($null -eq $status.ai) { return $null }
        return [bool]$status.ai.available
    } catch {
        return $null
    }
}

if ($Action -eq "stop") {
    $elevated = @()
    foreach ($name in @("ollama app", "ollama")) {
        foreach ($p in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) {
            # .Path is empty when the process has rights this window does not.
            # Asking Stop-Process anyway only produces the red stack.
            if (-not $p.Path) { $elevated += $p.Id; continue }
            Stop-Process -Id $p.Id -Force -Confirm:$false -ErrorAction SilentlyContinue
        }
    }
    # Said at once: the kill is instant, and the station shows it within the
    # five seconds of its next probe. The check below is for the presenter's
    # peace of mind, not something to wait on before talking.
    Write-Host "Assistant killed. Keep talking; the station notices within five seconds." -ForegroundColor Green
    if ($elevated.Count -gt 0) {
        Write-Host ("ollama.exe PID " + ($elevated -join ", ") + " runs with elevated rights and cannot be stopped from here. Reboot before the demo, or stop it from an administrator window.") -ForegroundColor Red
    }
    # Proved, not assumed: wait long enough for a supervisor to have restarted
    # it, then ask both ports.
    Start-Sleep -Seconds 6
    $view = Get-StationView $StationPort
    if ($view -eq $false) {
        Write-Host "Confirmed: the station on port $StationPort reports its assistant down. It stays down until: tools\assistant.ps1 start" -ForegroundColor DarkGray
        exit 0
    }
    if ($view -eq $true) {
        Write-Host "The station on port $StationPort STILL sees its assistant. Something restarted it, or it could not be stopped." -ForegroundColor Red
        exit 1
    }
    # No station answering: fall back to the ports themselves.
    $still = Get-AnsweringPorts
    if ($still.Count -gt 0) {
        Write-Host ("No station on port $StationPort to ask; Ollama is STILL answering on port " + ($still -join ", ") + ".") -ForegroundColor Red
        exit 1
    }
    Write-Host "Confirmed down after 6 s (no station running to ask; ports 11434 and 11555 are silent)." -ForegroundColor DarkGray
    exit 0
}

if ($Action -eq "start") {
    if ($Bundle) {
        $exe = Join-Path $Bundle "runtime\ollama\ollama.exe"
        if (-not (Test-Path -LiteralPath $exe)) {
            Write-Host "No bundled Ollama at $exe" -ForegroundColor Red
            exit 1
        }
        if (Test-Answering $BUNDLE_PORT) {
            Write-Host "The bundled assistant is already running." -ForegroundColor Green
            exit 0
        }
        # The same environment the launcher gives its own child, so the model
        # store and the port match what the running station expects.
        $env:OLLAMA_HOST = "127.0.0.1:$BUNDLE_PORT"
        $env:OLLAMA_MODELS = Join-Path $Bundle "models\ollama"
        Start-Process -FilePath $exe -ArgumentList "serve" -WorkingDirectory $Bundle -WindowStyle Hidden
        $port = $BUNDLE_PORT
    } else {
        if (Test-Answering $INSTALLED_PORT) {
            Write-Host "The assistant is already running." -ForegroundColor Green
            exit 0
        }
        if (-not (Test-Path -LiteralPath $APP)) {
            Write-Host "Ollama is not installed at $APP. Run setup.ps1." -ForegroundColor Red
            exit 1
        }
        # --hide --fast-startup: what the tray autostart uses. Without them the app
        # opens its own chat window on top of the demo (seen by Eddy, 24 Sep).
        # The same two cache slots the launcher gives it (tools\demarrer.ps1).
        $env:OLLAMA_NUM_PARALLEL = "2"
        $env:OLLAMA_KEEP_ALIVE = "2h"
        Start-Process -FilePath $APP -ArgumentList "--hide", "--fast-startup"
        $port = $INSTALLED_PORT
    }
    foreach ($i in 1..30) {
        Start-Sleep -Seconds 1
        if (Test-Answering $port) {
            Write-Host "Assistant back after $i s on port $port. The station notices within five more." -ForegroundColor Green
            exit 0
        }
    }
    Write-Host "Ollama was launched but is not answering on port $port after 30 s." -ForegroundColor Red
    exit 1
}

Write-Host "Usage: powershell -ExecutionPolicy Bypass -File tools\assistant.ps1 stop|start [-Bundle <folder>] [-StationPort 8765]"
