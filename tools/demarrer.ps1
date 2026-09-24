# The one double-click, from the working copy (Desktop\MedBox), on a machine
# where Ollama is installed: DEMARRER-LA-DEMO.cmd at the root runs this.
#
#   1. If MedBox already answers on its port, open the browser and stop.
#   2. If the installed Ollama is silent, start it (tray app, hidden).
#   3. Start the station in this window (medbox.py, the six personal pages).
#   4. When it answers, open the browser. Closing this window stops it all.
#
# It refuses nothing but a taken port and a missing .venv: the station runs
# without its assistant, and the page says so. Eddy, 24 Sep: "I just want to
# be able to click on it on my PC and it opens up properly."
#
# Pure ASCII on purpose: a BOM-less .ps1 is decoded with the system code page.

param([int]$Port = 0)

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")
$root = (Get-Location).Path
$APP = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama app.exe"
$OLLAMA_PORT = 11434

function Say([string]$t)  { Write-Host ("  " + $t) }
function Good([string]$t) { Write-Host ("  OK        " + $t) -ForegroundColor Green }
function Warn([string]$t) { Write-Host ("  ATTENTION " + $t) -ForegroundColor Yellow }
function Bad([string]$t)  { Write-Host ("  ECHEC     " + $t) -ForegroundColor Red }

# A raw connect, one second, no proxy detection (see tools\assistant.ps1).
function Test-Port([int]$P) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { return $client.ConnectAsync("127.0.0.1", $P).Wait(1000) } catch { return $false } finally { $client.Close() }
}

# True when a MedBox station answers there, not merely something on the port.
function Test-Station([int]$P) {
    try {
        $req = [System.Net.HttpWebRequest]::Create("http://127.0.0.1:$P/api/status")
        $req.Proxy = $null
        $req.Timeout = 2000
        $resp = $req.GetResponse()
        $reader = New-Object IO.StreamReader($resp.GetResponseStream())
        $body = $reader.ReadToEnd()
        $reader.Close(); $resp.Close()
        $status = $body | ConvertFrom-Json
        return ($null -ne $status.ship)
    } catch { return $false }
}

function Config([string]$section, [string]$name) {
    $current = ""
    foreach ($line in Get-Content -LiteralPath (Join-Path $root "config.toml")) {
        $s = ($line -split "#", 2)[0].Trim()
        if ($s -match '^\[(.+)\]$') { $current = $Matches[1]; continue }
        if ($current -eq $section -and $s -match ("^" + [regex]::Escape($name) + '\s*=\s*"?([^"]*)"?$')) { return $Matches[1] }
    }
    return ""
}

if ($Port -eq 0) { $Port = [int](Config "server" "port") }
if ($Port -eq 0) { $Port = 8765 }
$url = "http://127.0.0.1:$Port"

Write-Host ""
Write-Host "MedBox - demarrage depuis $root"
Write-Host "=================================================================="

$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
    Bad ".venv absent : lancer setup.ps1 une fois, puis relancer ce fichier."
    exit 1
}

# 1. Already running? Then the browser is all that is missing.
if (Test-Port $Port) {
    if (Test-Station $Port) {
        Good "MedBox tourne deja sur $url : j'ouvre le navigateur."
        Start-Process $url
        exit 0
    }
    $owner = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    $name = ""
    if ($owner) { $name = (Get-Process -Id $owner.OwningProcess -ErrorAction SilentlyContinue).ProcessName }
    Bad "Le port $Port est pris par un autre programme ($name). Fermer ce programme, ou changer port dans config.toml, puis relancer."
    exit 1
}

# 2. The installed Ollama, restarted from here so that it inherits
#    OLLAMA_NUM_PARALLEL=2: two cache slots, so a question's prompt prefix
#    survives an assessment in between (measured 24 Sep: 3-5 s instead of
#    6-10 s during the scenario). The tray app passes its environment to
#    the server it supervises; nothing is written to the machine. An
#    ollama.exe with elevated rights cannot be stopped from here: then the
#    running one is used as it is.
$env:OLLAMA_NUM_PARALLEL = "2"
$env:OLLAMA_KEEP_ALIVE = "2h"
if (-not (Test-Path -LiteralPath $APP)) {
    Warn "Ollama n'est pas installe ($APP) : la station demarre sans assistant (la page le dit)."
} else {
    $elevated = @(Get-Process -Name "ollama", "ollama app" -ErrorAction SilentlyContinue | Where-Object { -not $_.Path })
    if ($elevated.Count -gt 0 -and (Test-Port $OLLAMA_PORT)) {
        Warn "Un ollama.exe tourne avec des droits eleves (PID $(($elevated | ForEach-Object { $_.Id }) -join ', ')) : je l'utilise tel quel."
    } else {
        $running = @(Get-Process -Name "ollama", "ollama app" -ErrorAction SilentlyContinue)
        if ($running.Count -gt 0) {
            Say "Ollama : je le relance avec deux emplacements de cache."
            foreach ($p in $running) { Stop-Process -Id $p.Id -Force -Confirm:$false -ErrorAction SilentlyContinue }
            for ($i = 0; $i -lt 10; $i++) { if (-not (Test-Port $OLLAMA_PORT)) { break }; Start-Sleep -Seconds 1 }
        } else {
            Say "Ollama ne tourne pas : je le lance (barre systeme, cache)."
        }
        # --hide --fast-startup: what the tray autostart uses. Without them the
        # app opens its own chat window on top of the demo (seen 24 Sep).
        Start-Process -FilePath $APP -ArgumentList "--hide", "--fast-startup"
        $up = $false
        for ($i = 0; $i -lt 25; $i++) { Start-Sleep -Seconds 1; if (Test-Port $OLLAMA_PORT) { $up = $true; break } }
        if ($up) { Good "Ollama en ecoute sur le port $OLLAMA_PORT, deux emplacements de cache" } else { Warn "Ollama ne repond pas : la station demarre sans assistant (la page le dit)." }
    }
}

# 3. One line on memory: under 4 GB free the model reads from the disk.
$os = Get-CimInstance Win32_OperatingSystem
$ramFree = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
if ($ramFree -lt 4) {
    $hogs = (Get-Process | Where-Object { $_.Name -match '^(chrome|firefox|Spotify|WhatsApp|Teams|Discord|ProtonVPN|OneDrive|msedge)$' } |
        Group-Object Name | ForEach-Object { "{0} ({1:N0} Mo)" -f $_.Name, (($_.Group | Measure-Object WorkingSet64 -Sum).Sum / 1MB) }) -join ", "
    Warn "$ramFree Go de memoire vive libre : pour des reponses en quelques secondes, fermer $hogs"
} else {
    Good "$ramFree Go de memoire vive libre"
}

# 4. The station, in this window. Closing the window stops it.
Say "Demarrage de la station (six espaces personnels compris)..."
Write-Host ""
$proc = Start-Process -FilePath $py -ArgumentList "medbox.py" -WorkingDirectory $root -NoNewWindow -PassThru
$ready = $false
for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    if ($proc.HasExited) { break }
    if (Test-Station $Port) { $ready = $true; break }
}
if (-not $ready) {
    Write-Host ""
    if ($proc.HasExited) { Bad "La station s'est arretee avant de repondre : lis les lignes ci-dessus." }
    else { Bad "La station ne repond pas apres 90 s sur $url." }
    exit 1
}

# 5. The browser, then this window stays as the station's own.
Start-Process $url
Write-Host ""
Write-Host "=================================================================="
Good "MedBox repond sur $url : le navigateur s'ouvre."
Say "Espaces personnels : ports $($Port + 6) a $($Port + 11) (Eddy, Brad, Davidson, Anthony, Frederic, Merove)."
Say "L'assistant prechauffe : la puce passe a << pret >> en moins d'une minute."
Say "GARDER CETTE FENETRE OUVERTE pendant la demo. La fermer arrete MedBox."
Write-Host "=================================================================="
Write-Host ""
$proc.WaitForExit()
exit $proc.ExitCode
