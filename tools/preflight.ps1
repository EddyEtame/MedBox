# Friday-morning preflight. Run it before the jury, from the repo folder:
#   powershell -ExecutionPolicy Bypass -File tools\preflight.ps1
#   powershell -ExecutionPolicy Bypass -File tools\preflight.ps1 -Bundle D:\MedBox-Portable
#
# It changes nothing. It says, in one screen, whether this machine can run the
# demo: the port, the pinned Ollama and its model, the 59 French clips, the
# speech model, the disk, the network, the things that interrupt a demo. Every
# line is OK, ATTENTION or ECHEC, and the last line is the verdict.
#
# ASCII only, on purpose (see setup.ps1). French without accents is a price
# worth paying for a script that cannot be mis-decoded on the day.

param(
    [string]$Bundle = "",
    [int]$Port = 0,
    [switch]$RunTests
)

$ErrorActionPreference = "Continue"
Set-Location -LiteralPath (Join-Path $PSScriptRoot "..")
$root = (Get-Location).Path
$script:fails = 0
$script:warns = 0

function Ok([string]$t)   { Write-Host ("  OK        " + $t) -ForegroundColor Green }
function Warn([string]$t) { Write-Host ("  ATTENTION " + $t) -ForegroundColor Yellow; $script:warns++ }
function Fail([string]$t) { Write-Host ("  ECHEC     " + $t) -ForegroundColor Red; $script:fails++ }
function Section([string]$t) { Write-Host ""; Write-Host $t; Write-Host ("-" * $t.Length) }

function Config([string]$section, [string]$name) {
    $current = ""
    foreach ($line in Get-Content -LiteralPath (Join-Path $root "config.toml")) {
        $s = ($line -split "#", 2)[0].Trim()
        if ($s -match '^\[(.+)\]$') { $current = $Matches[1]; continue }
        if ($current -eq $section -and $s -match ("^" + [regex]::Escape($name) + '\s*=\s*"?([^"]*)"?$')) { return $Matches[1] }
    }
    return ""
}

Write-Host ""
Write-Host "MedBox - verification avant la soutenance   $(Get-Date -Format 'ddd dd MMM HH:mm')"
Write-Host "=================================================================="

Section "1. Machine"
$free = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
if ($free -lt 2) { Fail "C: $free Go libres. Sous 2 Go, Windows et Ollama commencent a echouer." }
elseif ($free -lt 5) { Warn "C: $free Go libres. Suffisant pour la demo, pas pour une installation." }
else { Ok "C: $free Go libres" }
$plan = (powercfg /getactivescheme 2>$null) -join " "
if ($plan -match "Balanced|Utilisation normale|Economie|Power saver") { Warn "Mode d'alimentation : $($plan -replace '.*\((.*)\).*','$1'). Sur secteur, choisir Performances." }
else { Ok "Mode d'alimentation : $($plan -replace '.*\((.*)\).*','$1')" }
$battery = Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue
if ($battery -and $battery.BatteryStatus -ne 2) { Warn "Sur batterie ($($battery.EstimatedChargeRemaining)%). Brancher le secteur : le modele est deux fois plus lent sur batterie." }
elseif ($battery) { Ok "Sur secteur ($($battery.EstimatedChargeRemaining)%)" }
$up = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Status -eq "Up" -and $_.Name -notmatch "Loopback|vEthernet|VirtualBox|VMware" }
if ($up) { Warn ("Reseau actif : " + (($up | ForEach-Object { $_.Name }) -join ", ") + ". La demo est hors ligne : mode avion recommande.") }
else { Ok "Aucun reseau actif : la station est bien hors ligne" }
$updates = Join-Path $env:LOCALAPPDATA "Ollama\updates_v2"
if (Test-Path -LiteralPath $updates) { Fail "Une mise a jour d'Ollama attend dans $updates : un clic la remplace. Deplacer ce dossier." }
else { Ok "Aucune mise a jour d'Ollama en attente" }
$dnd = Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Notifications\Settings" -Name NOC_GLOBAL_SETTING_TOASTS_ENABLED -ErrorAction SilentlyContinue
if ($dnd -and $dnd.NOC_GLOBAL_SETTING_TOASTS_ENABLED -eq 0) { Ok "Notifications Windows coupees" } else { Warn "Notifications Windows actives : activer Ne pas deranger avant de projeter." }

Section "2. Port"
if ($Port -eq 0) { $Port = [int](Config "server" "port") }
if ($Port -eq 0) { $Port = 8765 }
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    $proc = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
    $status = $null
    try { $status = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 "http://127.0.0.1:$Port/api/status").Content | ConvertFrom-Json } catch {}
    if ($status -and $status.ship) { Ok "Port $Port : MedBox repond deja (assistant : $($status.ai.available), prechauffe : $($status.ai.warmed))" }
    else { Fail "Port $Port occupe par $($proc.ProcessName) (PID $($listener.OwningProcess)). La station ne pourra pas demarrer la." }
} else { Ok "Port $Port libre" }
$pem = Get-Service PEMHTTPD-x64 -ErrorAction SilentlyContinue
if ($pem -and $pem.Status -eq "Running") { Warn "Le service PEMHTTPD-x64 tourne et tient le port 8080. Sans effet sur $Port ; inutile pendant la demo." }

Section "3. Ollama et le modele"
$pin = Config "ai" "required_ollama"
$model = Config "ai" "model"
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path -LiteralPath $ollama)) { $cmd = Get-Command ollama -ErrorAction SilentlyContinue; if ($cmd) { $ollama = $cmd.Source } }
if (-not (Test-Path -LiteralPath $ollama)) { Fail "ollama.exe introuvable" }
else {
    $ver = (& $ollama --version 2>&1 | Out-String)
    if ($ver -match '(\d+\.\d+\.\d+)') { $v = $Matches[1]; if ($v -eq $pin) { Ok "Ollama $v = version epinglee" } else { Fail "Ollama $v, config.toml epingle $pin" } }
    else { Fail "Ollama ne repond pas a --version : $ver" }
    $global:LASTEXITCODE = $null
    $list = (& $ollama list 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { Fail "ollama list echoue : le serveur ne tourne pas. Lancer Ollama depuis le menu Demarrer." }
    elseif ($list -match [regex]::Escape($model)) { Ok "Modele $model present" }
    else { Fail "Modele $model absent de ollama list" }
}

Section "4. Voix et oreilles"
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) { Fail ".venv absent : lancer setup.ps1" }
else {
    $global:LASTEXITCODE = $null
    $clips = (& $py tools\render_speech.py --check 2>&1 | Out-String)
    if ($LASTEXITCODE -eq 0) { Ok ($clips.Trim() -split "`n" | Select-Object -Last 1) } else { Fail "Clips vocaux : $($clips.Trim())" }
    $consent = Join-Path $root "web\speech\consent_fr.wav"
    if (Test-Path -LiteralPath $consent) { Ok "Notice de consentement enregistree (consent_fr.wav)" } else { Fail "consent_fr.wav absent : la station ne se presentera pas a voix haute" }
    $speech = Join-Path $root "models\faster-whisper-base\model.bin"
    if (Test-Path -LiteralPath $speech) { Ok "Modele de reconnaissance vocale present" } else { Warn "Modele vocal absent : le micro restera cache (tools\assets.py)" }
}
$voices = @()
try { Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $voices = $s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Culture.Name }; $s.Dispose() } catch {}
if ($voices -match '^fr') { Ok "Voix Windows francaise disponible (secours)" } else { Ok "Pas de voix Windows francaise : les clips Piper font tout, comme prevu" }

Section "5. Dossier portable"
if ($Bundle) {
    $exe = Join-Path $Bundle "MedBox.exe"
    $manifest = Join-Path $Bundle "manifests\bundle-manifest.json"
    if (Test-Path -LiteralPath $exe) { Ok "MedBox.exe present dans $Bundle" } else { Fail "MedBox.exe absent de $Bundle" }
    if (Test-Path -LiteralPath $manifest) {
        $m = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
        $parts = @()
        foreach ($k in @("ollama", "model", "speech")) { if ($m.PSObject.Properties.Name -contains $k) { $parts += "$k=$($m.$k)" } }
        Ok ("Manifeste : " + ($parts -join " "))
    } else { Warn "Pas de manifeste : le contenu du dossier n'est pas verifiable" }
} else { Warn "Aucun dossier portable indique (-Bundle D:\MedBox-Portable) : la demo tournera depuis ce depot" }

if ($RunTests -and (Test-Path -LiteralPath $py)) {
    Section "6. Tests"
    $global:LASTEXITCODE = $null
    $out = (& $py -m pytest tests -q -p no:cacheprovider 2>&1 | Out-String)
    $last = ($out.Trim() -split "`n" | Select-Object -Last 1)
    if ($LASTEXITCODE -eq 0) { Ok $last } else { Fail $last }
}

Write-Host ""
Write-Host "=================================================================="
if ($script:fails -gt 0) { Write-Host "$($script:fails) point(s) bloquant(s), $($script:warns) a regarder. Ne pas presenter avant de les regler." -ForegroundColor Red; exit 1 }
elseif ($script:warns -gt 0) { Write-Host "Pret, avec $($script:warns) point(s) a regarder." -ForegroundColor Yellow; exit 0 }
else { Write-Host "Pret." -ForegroundColor Green; exit 0 }
