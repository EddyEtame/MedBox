# Kill the assistant on stage, and bring it back, on Windows.
#   powershell -ExecutionPolicy Bypass -File tools\assistant.ps1 stop
#   powershell -ExecutionPolicy Bypass -File tools\assistant.ps1 start
#
# Why this exists: on Windows, Ollama is two processes. "ollama app.exe" sits in
# the tray and "ollama.exe" is the server it supervises. End the server alone -
# Task Manager, taskkill, Stop-Process - and the tray app starts a new one.
# Measured on the demo machine: a new server was answering five seconds later,
# and the station showed the assistant as back while the presenter was still
# saying it was gone. So the tray app goes first, then the server.
#
# Pure ASCII on purpose: a BOM-less .ps1 is decoded with the system code page.

param([string]$Action = "")

# Not "Stop": see setup.ps1 for what that does to native programs' stderr.
$ErrorActionPreference = "Continue"

$APP = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"

# A raw TCP connect, not Invoke-WebRequest: the first web request in a fresh
# PowerShell 5.1 spends seconds on proxy auto-detection, and the first version
# of this script took twenty seconds to say "stopped" in front of an audience.
function Test-Answering {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        return $client.ConnectAsync("127.0.0.1", 11434).Wait(1000)
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

if ($Action -eq "stop") {
    Get-Process -Name "ollama app" -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:$false
    Get-Process -Name "ollama" -ErrorAction SilentlyContinue | Stop-Process -Force -Confirm:$false
    # Said at once: the kill is instant, and the station shows it within the
    # five seconds of its next probe. The check below is for the presenter's
    # peace of mind, not something to wait on before talking.
    Write-Host "Assistant killed. Keep talking; the station notices within five seconds." -ForegroundColor Green
    # Proved, not assumed: wait long enough for a supervisor to have restarted
    # it, then ask.
    Start-Sleep -Seconds 6
    if (Test-Answering) {
        Write-Host "It is STILL answering. Something restarted it." -ForegroundColor Red
        exit 1
    }
    Write-Host "Confirmed down after 6 s. It stays down until: tools\assistant.ps1 start" -ForegroundColor DarkGray
    exit 0
}

if ($Action -eq "start") {
    if (Test-Answering) {
        Write-Host "The assistant is already running." -ForegroundColor Green
        exit 0
    }
    if (-not (Test-Path -LiteralPath $APP)) {
        Write-Host "Ollama is not installed at $APP. Run setup.ps1." -ForegroundColor Red
        exit 1
    }
    Start-Process -FilePath $APP
    foreach ($i in 1..30) {
        Start-Sleep -Seconds 1
        if (Test-Answering) {
            Write-Host "Assistant back after $i s. The station notices within five more." -ForegroundColor Green
            exit 0
        }
    }
    Write-Host "Ollama was launched but is not answering after 30 s." -ForegroundColor Red
    exit 1
}

Write-Host "Usage: powershell -ExecutionPolicy Bypass -File tools\assistant.ps1 stop|start"
exit 2
