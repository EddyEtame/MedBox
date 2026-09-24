# Friday-morning preflight. Run it before the jury, from the repo folder or
# from the portable folder (DEMARRER-LA-DEMO.cmd runs it, then launches):
#   powershell -ExecutionPolicy Bypass -File tools\preflight.ps1
#   powershell -ExecutionPolicy Bypass -File tools\preflight.ps1 -Bundle D:\MedBox-Portable
#
# It changes nothing. It says, in one screen, whether this machine can run the
# demo: the memory, the port, the pinned Ollama and its model, the French
# clips, the speech model, the disk, the network, the things that interrupt a
# demo. Every line is OK, ATTENTION or ECHEC, and the last line is the verdict.
#
# Two homes, told apart by where config.toml sits: the repo (config.toml at the
# root, .venv, the Ollama installed on the machine) and the portable folder
# (app\config.toml, runtime\python, runtime\ollama, models\ollama). Measured
# 24 Sep: run from the portable folder, the repo checks reported three
# blockers on a folder that was ready.
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
$portable = Test-Path -LiteralPath (Join-Path $root "app\config.toml")
if ($portable) { $app = Join-Path $root "app" } else { $app = $root }
if ($portable -and -not $Bundle) { $Bundle = $root }
$script:fails = 0
$script:warns = 0

function Ok([string]$t)   { Write-Host ("  OK        " + $t) -ForegroundColor Green }
function Warn([string]$t) { Write-Host ("  ATTENTION " + $t) -ForegroundColor Yellow; $script:warns++ }
function Fail([string]$t) { Write-Host ("  ECHEC     " + $t) -ForegroundColor Red; $script:fails++ }
function Section([string]$t) { Write-Host ""; Write-Host $t; Write-Host ("-" * $t.Length) }

# A raw connect, one second, no proxy detection (see tools\assistant.ps1).
function Test-Port([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try { return $client.ConnectAsync("127.0.0.1", $Port).Wait(1000) } catch { return $false } finally { $client.Close() }
}

function Config([string]$section, [string]$name) {
    $current = ""
    foreach ($line in Get-Content -LiteralPath (Join-Path $app "config.toml")) {
        $s = ($line -split "#", 2)[0].Trim()
        if ($s -match '^\[(.+)\]$') { $current = $Matches[1]; continue }
        if ($current -eq $section -and $s -match ("^" + [regex]::Escape($name) + '\s*=\s*"?([^"]*)"?$')) { return $Matches[1] }
    }
    return ""
}

Write-Host ""
Write-Host "MedBox - verification avant la soutenance   $(Get-Date -Format 'ddd dd MMM HH:mm')"
if ($portable) { Write-Host "Dossier portable : $root" } else { Write-Host "Depot : $root" }
Write-Host "=================================================================="

Section "1. Machine"
$free = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
if ($free -lt 2) { Fail "C: $free Go libres. Sous 2 Go, Windows et Ollama commencent a echouer." }
# La memoire vive: le modele lit son texte a 10 mots par seconde quand Windows
# le met sur le disque (24 septembre : 1,7 Go libres, reponses hors delai).
$os = Get-CimInstance Win32_OperatingSystem
$ramFree = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
$hogs = (Get-Process | Where-Object { $_.Name -match '^(chrome|firefox|Spotify|WhatsApp|Teams|Discord|ProtonVPN|OneDrive|msedge)$' } |
    Group-Object Name | ForEach-Object { "{0} ({1:N0} Mo)" -f $_.Name, (($_.Group | Measure-Object WorkingSet64 -Sum).Sum / 1MB) }) -join ", "
if ($ramFree -lt 2.5) { Fail "$ramFree Go de memoire vive libre : le modele sera mis sur le disque. Fermer avant la demo : $hogs" }
elseif ($ramFree -lt 4) { Warn "$ramFree Go de memoire vive libre. Pour des reponses en quelques secondes, fermer : $hogs" }
else { Ok "$ramFree Go de memoire vive libre" }
$ollamas = @(Get-CimInstance Win32_Process -Filter "Name='ollama.exe'" | Where-Object { $_.CommandLine -match ' serve' })
if ($ollamas.Count -gt 1) { Warn "$($ollamas.Count) serveurs Ollama tournent (menu Demarrer et dossier portable) : quitter celui de la barre des taches" }
elseif ($free -lt 5) { Warn "C: $free Go libres. Suffisant pour la demo, pas pour une installation." }
else { Ok "C: $free Go libres" }
# The tray Ollama loads its own copy of the model next to the bundle's:
# 24 Sep, 2.8 GB of duplicate runners on a laptop with 0.8 GB free.
$tray = @(Get-Process -Name "ollama app" -ErrorAction SilentlyContinue)
if ($portable -and $tray.Count -gt 0) { Warn "Ollama de la barre systeme tourne : le quitter (clic droit sur l'icone pres de l'horloge, Quit). Il double la memoire du modele." }
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
if (Test-Path -LiteralPath $updates) {
    # The portable folder runs its own Ollama; the update only matters if the
    # tray one is used, or clicked.
    if ($portable) { Warn "Une mise a jour de l'Ollama installe attend dans $updates : ne pas cliquer dessus pendant la demo (le dossier portable a le sien)." }
    else { Fail "Une mise a jour d'Ollama attend dans $updates : un clic la remplace. Deplacer ce dossier." }
}
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
if ($portable) {
    # The folder carries its own Ollama and model; nothing is asked of the
    # machine, and no CLI is called: the launcher starts the server itself.
    $ollama = Join-Path $root "runtime\ollama\ollama.exe"
    if (Test-Path -LiteralPath $ollama) { Ok "Ollama embarque : runtime\ollama\ollama.exe" } else { Fail "runtime\ollama\ollama.exe absent : le dossier est incomplet" }
    $manifest = Join-Path $root "manifests\bundle-manifest.json"
    $shipped = ""
    if (Test-Path -LiteralPath $manifest) { try { $shipped = (Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json).components.ollama.requiredVersion } catch {} }
    if ($shipped -and $pin -and $shipped -eq $pin) { Ok "Ollama $shipped = version epinglee" }
    elseif ($shipped -and $pin) { Fail "Ollama $shipped embarque, config.toml epingle $pin" }
    else { Warn "Version d'Ollama non verifiable (manifeste ou epingle absent)" }
    $parts = $model -split ":", 2
    if ($parts.Count -eq 2) { $modelDir = Join-Path $root ("models\ollama\manifests\registry.ollama.ai\library\" + $parts[0] + "\" + $parts[1]) } else { $modelDir = "" }
    if ($modelDir -and (Test-Path -LiteralPath $modelDir)) { Ok "Modele $model embarque" } else { Fail "Modele $model absent de models\ollama" }
    if (-not (Test-Port 11434)) { Ok "Rien sur le port 11434 : l'Ollama de la machine ne tourne pas, le dossier portable a le sien" }
}
else {
    $ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (-not (Test-Path -LiteralPath $ollama)) { $cmd = Get-Command ollama -ErrorAction SilentlyContinue; if ($cmd) { $ollama = $cmd.Source } }
    if (-not (Test-Path -LiteralPath $ollama)) { Fail "ollama.exe introuvable" }
    elseif (-not (Test-Port 11434)) {
        # Never call the CLI while the server is down: on Windows it launches the
        # tray app, which inherits this script's output pipe, and Out-String then
        # waits for an end of stream that never comes. Seen: a preflight with no
        # output for three minutes, killed by hand.
        Fail "Ollama ne repond pas sur le port 11434 : lancer tools\assistant.ps1 start, puis relancer ce script."
    }
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
}
# An ollama.exe with rights this window does not have (.Path stays empty)
# survives tools\assistant.ps1 stop: the kill moment would fail on stage.
$elevated = @(Get-Process -Name ollama -ErrorAction SilentlyContinue | Where-Object { -not $_.Path } | ForEach-Object { $_.Id })
if ($elevated.Count -gt 0) { Fail ("ollama.exe PID " + ($elevated -join ", ") + " tourne avec des droits eleves : assistant.ps1 stop ne pourra pas le tuer sur scene. Redemarrer la machine avant la soutenance.") }
else { Ok "Aucun ollama.exe avec des droits eleves : le moment ou on le tue fonctionnera" }

Section "4. Voix et oreilles"
if ($portable) { $py = Join-Path $root "runtime\python\python.exe" } else { $py = Join-Path $root ".venv\Scripts\python.exe" }
if (-not (Test-Path -LiteralPath $py)) {
    if ($portable) { Fail "runtime\python\python.exe absent : le dossier est incomplet" } else { Fail ".venv absent : lancer setup.ps1" }
}
else {
    if ($portable) {
        $clips = @(Get-ChildItem -LiteralPath (Join-Path $app "web\speech") -Filter "*.wav" -ErrorAction SilentlyContinue)
        if ($clips.Count -ge 50) { Ok "$($clips.Count) clips vocaux embarques" } else { Fail "$($clips.Count) clips vocaux dans app\web\speech : il en faut une soixantaine" }
    }
    else {
        $global:LASTEXITCODE = $null
        $clips = (& $py tools\render_speech.py --check 2>&1 | Out-String)
        if ($LASTEXITCODE -eq 0) { Ok ($clips.Trim() -split "`n" | Select-Object -Last 1) } else { Fail "Clips vocaux : $($clips.Trim())" }
    }
    $consent = Join-Path $app "web\speech\consent_fr.wav"
    if (Test-Path -LiteralPath $consent) { Ok "Notice de consentement enregistree (consent_fr.wav)" } else { Fail "consent_fr.wav absent : la station ne se presentera pas a voix haute" }
    $speech = Join-Path $app "models\faster-whisper-base\model.bin"
    if (Test-Path -LiteralPath $speech) { Ok "Modele de reconnaissance vocale present" } else { Warn "Modele vocal absent : le micro restera cache (tools\assets.py)" }
    $voice = Join-Path $app "models\piper\fr_FR-siwis-medium.onnx"
    if (Test-Path -LiteralPath $voice) { Ok "Voix Piper embarquee : l'assistant lit ses reponses" } else { Warn "Voix Piper absente (models\piper) : l'assistant reste muet, les clips suffisent" }
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
        $c = $m.components
        $commit = ""
        if ($m.source -and $m.source.commit) { $commit = $m.source.commit.Substring(0, 7); if ($m.source.dirty) { $commit += " (arbre modifie, non commite)" } }
        $summary = "commit $commit ; Ollama " + $(if ($c.ollama.present) { "inclus" } else { "ABSENT" }) + " ; modele " + $(if ($c.model.present) { $c.model.name } else { "ABSENT" }) + " ; voix " + $(if ($c.speechModel.present) { "incluse" } else { "ABSENTE" })
        if ($m.readiness.completeForVoiceDemo) { Ok ("Manifeste : " + $summary) } else { Fail ("Manifeste incomplet pour la demo vocale : " + $summary) }
        if ($m.source -and $m.source.dirty) { Warn "Le dossier a ete construit depuis un arbre non commite : le manifeste ne prouve pas quel code il contient." }
    } else { Warn "Pas de manifeste : le contenu du dossier n'est pas verifiable" }
} else { Warn "Aucun dossier portable indique (-Bundle D:\MedBox-Portable) : la demo tournera depuis ce depot" }

if ($RunTests -and -not $portable -and (Test-Path -LiteralPath $py)) {
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
