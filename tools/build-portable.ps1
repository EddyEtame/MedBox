[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [ValidateSet("Preflight", "Build", "Check", "Smoke")]
    [string]$Mode = "Build",

    [string]$PythonRuntime,
    [string]$PythonSha256,
    [string]$DependencyPython,
    [string]$Wheelhouse,
    [string]$OllamaRuntime,
    [string]$OllamaModels,
    [string]$SpeechModel,
    [string[]]$ExtraDocument = @(),
    [switch]$AllowNetwork,
    [switch]$RequireComplete,
    [double]$MinimumFreeGB = 6
)

# This file intentionally contains ASCII only. Windows PowerShell 5.1 reads a
# BOM-less .ps1 through the active ANSI code page, not as UTF-8.
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Destination = [IO.Path]::GetFullPath($Destination)
$script:Blockers = New-Object System.Collections.Generic.List[string]
$script:Warnings = New-Object System.Collections.Generic.List[string]

function Write-Step([string]$Text) {
    Write-Host "`n== $Text ==" -ForegroundColor Cyan
}

function Add-Blocker([string]$Text) {
    $script:Blockers.Add($Text)
    Write-Host "BLOCKER: $Text" -ForegroundColor Red
}

function Add-Warning([string]$Text) {
    $script:Warnings.Add($Text)
    Write-Host "WARNING: $Text" -ForegroundColor Yellow
}

function Assert-SafeDestination([string]$Path) {
    $full = [IO.Path]::GetFullPath($Path)
    $root = [IO.Path]::GetPathRoot($full)
    if ([string]::IsNullOrWhiteSpace($root) -or $full.TrimEnd('\') -eq $root.TrimEnd('\')) {
        throw "Destination must be a named folder, never a drive root: $full"
    }
    if ($full.TrimEnd('\') -eq $RepoRoot.TrimEnd('\')) {
        throw "Destination cannot be the source repository."
    }
    if ($RepoRoot.StartsWith($full.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Destination cannot contain the source repository."
    }
    return $full
}

function Assert-SafeEphemeral([string]$Path, [string]$Parent, [string]$Prefix) {
    $full = [IO.Path]::GetFullPath($Path)
    $expectedParent = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    if ([IO.Path]::GetDirectoryName($full).TrimEnd('\') -ne $expectedParent) {
        throw "Refusing to remove a path outside the expected build parent: $full"
    }
    if (-not [IO.Path]::GetFileName($full).StartsWith($Prefix, [StringComparison]::Ordinal)) {
        throw "Refusing to remove a path without the build prefix: $full"
    }
}

function Remove-Ephemeral([string]$Path, [string]$Parent, [string]$Prefix) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    Assert-SafeEphemeral $Path $Parent $Prefix
    Remove-Item -LiteralPath $Path -Recurse -Force
}

function Get-ConfigValue([string]$Section, [string]$Name) {
    $current = ""
    foreach ($line in Get-Content -LiteralPath (Join-Path $RepoRoot "config.toml")) {
        $clean = ($line -split '#', 2)[0].Trim()
        if ($clean -match '^\[([^]]+)\]$') {
            $current = $Matches[1]
            continue
        }
        if ($current -eq $Section -and $clean -match ('^' + [regex]::Escape($Name) + '\s*=\s*["'']([^"'']+)["'']')) {
            return $Matches[1]
        }
    }
    return $null
}

function Get-CommandPath([string]$Name) {
    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $command) { return $null }
    return $command.Source
}

function Resolve-OptionalPath([string]$Explicit, [string]$EnvironmentName, [string]$Fallback) {
    if (-not [string]::IsNullOrWhiteSpace($Explicit)) {
        return [IO.Path]::GetFullPath($Explicit)
    }
    $fromEnvironment = [Environment]::GetEnvironmentVariable($EnvironmentName)
    if (-not [string]::IsNullOrWhiteSpace($fromEnvironment)) {
        return [IO.Path]::GetFullPath($fromEnvironment)
    }
    if (-not [string]::IsNullOrWhiteSpace($Fallback) -and (Test-Path -LiteralPath $Fallback)) {
        return [IO.Path]::GetFullPath($Fallback)
    }
    return $null
}

function Get-OllamaRuntimeSource {
    $fallback = $null
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $fallback = Join-Path $env:LOCALAPPDATA "Programs\Ollama"
    }
    return Resolve-OptionalPath $OllamaRuntime "MEDBOX_OLLAMA_RUNTIME" $fallback
}

function Get-OllamaModelsSource {
    $fallback = $null
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $fallback = Join-Path $env:USERPROFILE ".ollama\models"
    }
    return Resolve-OptionalPath $OllamaModels "MEDBOX_OLLAMA_MODELS" $fallback
}

function Get-SpeechModelSource {
    $fallback = Join-Path $RepoRoot "models\faster-whisper-base"
    return Resolve-OptionalPath $SpeechModel "MEDBOX_SPEECH_MODEL" $fallback
}

function Get-PythonRuntimeSource {
    return Resolve-OptionalPath $PythonRuntime "MEDBOX_PYTHON_RUNTIME" ""
}

function Get-WheelhouseSource {
    return Resolve-OptionalPath $Wheelhouse "MEDBOX_WHEELHOUSE" ""
}

function Get-RelativePath([string]$Base, [string]$Path) {
    $baseFull = [IO.Path]::GetFullPath($Base).TrimEnd('\') + '\'
    $pathFull = [IO.Path]::GetFullPath($Path)
    if (-not $pathFull.StartsWith($baseFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$pathFull is outside $baseFull"
    }
    return $pathFull.Substring($baseFull.Length)
}

function Copy-CleanTree([string]$Source, [string]$Target, [string[]]$ExcludeTopLevel = @()) {
    $sourceFull = [IO.Path]::GetFullPath($Source)
    if (-not (Test-Path -LiteralPath $sourceFull -PathType Container)) {
        throw "Source directory is missing: $sourceFull"
    }
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $sourceFull -Recurse -Force) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Reparse points are not accepted in a portable payload: $($item.FullName)"
        }
        $relative = Get-RelativePath $sourceFull $item.FullName
        $parts = $relative -split '[\\/]'
        if ($parts.Count -gt 0 -and $ExcludeTopLevel -contains $parts[0]) { continue }
        if ($parts -contains "__pycache__" -or $parts -contains ".pytest_cache") { continue }
        if (-not $item.PSIsContainer -and ($item.Extension -eq ".pyc" -or $item.Extension -eq ".pyo")) { continue }
        $destinationPath = Join-Path $Target $relative
        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
        } else {
            New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($destinationPath)) -Force | Out-Null
            Copy-Item -LiteralPath $item.FullName -Destination $destinationPath -Force
        }
    }
}

function Copy-App([string]$BundleRoot) {
    $app = Join-Path $BundleRoot "app"
    New-Item -ItemType Directory -Path $app -Force | Out-Null
    foreach ($file in @("medbox.py", "config.toml", "requirements.txt", "requirements-speech.txt", "README.md")) {
        $source = Join-Path $RepoRoot $file
        if (Test-Path -LiteralPath $source -PathType Leaf) {
            Copy-Item -LiteralPath $source -Destination (Join-Path $app $file) -Force
        }
    }
    foreach ($folder in @("server", "web", "scenarios")) {
        Copy-CleanTree (Join-Path $RepoRoot $folder) (Join-Path $app $folder)
    }
}

function Test-SpeechModel([string]$Source, [switch]$Quiet) {
    if ([string]::IsNullOrWhiteSpace($Source) -or -not (Test-Path -LiteralPath $Source -PathType Container)) {
        if (-not $Quiet) { Add-Warning "speech model missing; continuous local transcription will be unavailable" }
        return $false
    }
    foreach ($name in @("config.json", "model.bin", "tokenizer.json")) {
        if (-not (Test-Path -LiteralPath (Join-Path $Source $name) -PathType Leaf)) {
            if (-not $Quiet) { Add-Warning "speech model is incomplete: missing $name in $Source" }
            return $false
        }
    }
    return $true
}

function Get-OllamaModelClosure([string]$ModelsRoot, [string]$ModelName, [switch]$Quiet) {
    if ([string]::IsNullOrWhiteSpace($ModelsRoot) -or -not (Test-Path -LiteralPath $ModelsRoot -PathType Container)) {
        if (-not $Quiet) { Add-Warning "Ollama model store not found" }
        return $null
    }
    $pair = $ModelName -split ':', 2
    $repository = $pair[0]
    $tag = if ($pair.Count -gt 1) { $pair[1] } else { "latest" }
    if ($repository.Contains('/')) {
        $segments = $repository -split '/'
        if ($segments.Count -eq 2) {
            $namespace = $segments[0]
            $name = $segments[1]
        } else {
            if (-not $Quiet) { Add-Warning "unsupported Ollama model name for portable closure: $ModelName" }
            return $null
        }
    } else {
        $namespace = "library"
        $name = $repository
    }
    $relativeManifest = Join-Path (Join-Path (Join-Path "manifests\registry.ollama.ai" $namespace) $name) $tag
    $manifestPath = Join-Path $ModelsRoot $relativeManifest
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        if (-not $Quiet) { Add-Warning "configured Ollama model is absent: $ModelName" }
        return $null
    }
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    } catch {
        if (-not $Quiet) { Add-Warning "configured Ollama manifest is invalid JSON: $manifestPath" }
        return $null
    }
    $descriptors = @($manifest.config) + @($manifest.layers)
    $blobs = @()
    foreach ($descriptor in $descriptors) {
        $digest = [string]$descriptor.digest
        if ($digest -notmatch '^sha256:([0-9a-f]{64})$') {
            if (-not $Quiet) { Add-Warning "invalid model digest in ${manifestPath}: $digest" }
            return $null
        }
        $hex = $Matches[1]
        $blobPath = Join-Path (Join-Path $ModelsRoot "blobs") ("sha256-" + $hex)
        if (-not (Test-Path -LiteralPath $blobPath -PathType Leaf)) {
            if (-not $Quiet) { Add-Warning "configured model blob is missing: sha256-$hex" }
            return $null
        }
        $item = Get-Item -LiteralPath $blobPath
        if ($null -ne $descriptor.size -and [int64]$descriptor.size -ne $item.Length) {
            if (-not $Quiet) { Add-Warning "configured model blob has the wrong size: sha256-$hex" }
            return $null
        }
        $actual = (Get-FileHash -LiteralPath $blobPath -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $hex) {
            if (-not $Quiet) { Add-Warning "configured model blob failed SHA-256: sha256-$hex" }
            return $null
        }
        $blobs += [pscustomobject]@{
            Source = $blobPath
            Name = "sha256-$hex"
            Digest = "sha256:$hex"
            Size = $item.Length
            MediaType = [string]$descriptor.mediaType
        }
    }
    return [pscustomobject]@{
        Manifest = $manifestPath
        RelativeManifest = $relativeManifest
        Blobs = $blobs
        Name = $ModelName
    }
}

function Test-OllamaRuntime([string]$Source, [switch]$Quiet) {
    if ([string]::IsNullOrWhiteSpace($Source)) {
        if (-not $Quiet) { Add-Warning "Ollama runtime not found" }
        return $false
    }
    $exe = if (Test-Path -LiteralPath $Source -PathType Leaf) {
        $Source
    } else {
        Join-Path $Source "ollama.exe"
    }
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
        if (-not $Quiet) { Add-Warning "ollama.exe missing from $Source" }
        return $false
    }
    $required = Get-ConfigValue "ai" "required_ollama"
    $versionText = (& $exe --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $versionText -notmatch '(\d+\.\d+\.\d+)') {
        if (-not $Quiet) { Add-Warning "Ollama runtime did not report a readable version: $exe" }
        return $false
    }
    $actual = $Matches[1]
    if (-not [string]::IsNullOrWhiteSpace($required) -and $actual -ne $required) {
        if (-not $Quiet) { Add-Warning "Ollama $actual found, but config.toml requires $required" }
        return $false
    }
    return $true
}

function Copy-OllamaRuntime([string]$Source, [string]$Target) {
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    if (Test-Path -LiteralPath $Source -PathType Leaf) {
        Copy-Item -LiteralPath $Source -Destination (Join-Path $Target "ollama.exe") -Force
        return
    }
    Copy-Item -LiteralPath (Join-Path $Source "ollama.exe") -Destination (Join-Path $Target "ollama.exe") -Force
    $cpuLibSource = Join-Path $Source "lib\ollama"
    if (Test-Path -LiteralPath $cpuLibSource -PathType Container) {
        $cpuLibTarget = Join-Path $Target "lib\ollama"
        New-Item -ItemType Directory -Path $cpuLibTarget -Force | Out-Null
        foreach ($dll in Get-ChildItem -LiteralPath $cpuLibSource -File -Filter "*.dll") {
            Copy-Item -LiteralPath $dll.FullName -Destination (Join-Path $cpuLibTarget $dll.Name) -Force
        }
    }
}

function Copy-OllamaModel($Closure, [string]$TargetRoot, [string]$LicenseRoot) {
    $manifestTarget = Join-Path $TargetRoot $Closure.RelativeManifest
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($manifestTarget)) -Force | Out-Null
    Copy-Item -LiteralPath $Closure.Manifest -Destination $manifestTarget -Force
    $blobTarget = Join-Path $TargetRoot "blobs"
    New-Item -ItemType Directory -Path $blobTarget -Force | Out-Null
    foreach ($blob in $Closure.Blobs) {
        Copy-Item -LiteralPath $blob.Source -Destination (Join-Path $blobTarget $blob.Name) -Force
        if ($blob.MediaType -like "*license*") {
            New-Item -ItemType Directory -Path $LicenseRoot -Force | Out-Null
            Copy-Item -LiteralPath $blob.Source -Destination (Join-Path $LicenseRoot "qwen2.5-model-license.txt") -Force
        }
    }
}

function Prepare-Python([string]$Source, [string]$ExpectedHash, [string]$Target, [string]$Work) {
    if (-not (Test-Path -LiteralPath $Source)) { throw "Python runtime source is missing: $Source" }
    if (Test-Path -LiteralPath $Source -PathType Leaf) {
        if ([IO.Path]::GetExtension($Source) -ne ".zip") { throw "Python runtime archive must be a .zip: $Source" }
        if ([string]::IsNullOrWhiteSpace($ExpectedHash)) {
            throw "PythonSha256 is required for an archive so its origin is verified before extraction."
        }
        $actual = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $ExpectedHash.ToLowerInvariant()) {
            throw "Python runtime SHA-256 mismatch: expected $ExpectedHash, got $actual"
        }
        $extract = Join-Path $Work "python-extract"
        New-Item -ItemType Directory -Path $extract -Force | Out-Null
        Expand-Archive -LiteralPath $Source -DestinationPath $extract
        $python = Get-ChildItem -LiteralPath $extract -Recurse -File -Filter "python.exe" | Select-Object -First 1
        if ($null -eq $python) { throw "python.exe is absent from $Source" }
        Copy-CleanTree $python.Directory.FullName $Target
    } else {
        Copy-CleanTree $Source $Target
    }
    $targetPython = Join-Path $Target "python.exe"
    if (-not (Test-Path -LiteralPath $targetPython -PathType Leaf)) {
        throw "Portable Python must place python.exe at the runtime root: $Target"
    }
    $pth = Get-ChildItem -LiteralPath $Target -File -Filter "python*._pth" | Select-Object -First 1
    if ($null -ne $pth) {
        $lines = @(Get-Content -LiteralPath $pth.FullName)
        $lines = @($lines | ForEach-Object { if ($_.Trim() -eq "#import site") { "import site" } else { $_ } })
        if (-not ($lines -contains "Lib\site-packages")) { $lines += "Lib\site-packages" }
        [IO.File]::WriteAllLines($pth.FullName, $lines, (New-Object Text.UTF8Encoding($false)))
    }
    New-Item -ItemType Directory -Path (Join-Path $Target "Lib\site-packages") -Force | Out-Null
}

function Install-PythonDependencies([string]$PortablePython, [string]$Target, [string]$Work, [string]$WheelSource, [bool]$IncludeSpeech) {
    $builderPython = $DependencyPython
    if ([string]::IsNullOrWhiteSpace($builderPython)) { $builderPython = Get-CommandPath "python.exe" }
    if ([string]::IsNullOrWhiteSpace($builderPython) -or -not (Test-Path -LiteralPath $builderPython -PathType Leaf)) {
        throw "A Python 3.11 build interpreter is required (use -DependencyPython)."
    }
    $site = Join-Path $Target "Lib\site-packages"
    $requirements = @((Join-Path $RepoRoot "requirements.txt"))
    if ($IncludeSpeech) { $requirements += (Join-Path $RepoRoot "requirements-speech.txt") }
    $arguments = @("-m", "pip", "install", "--disable-pip-version-check", "--no-compile", "--only-binary=:all:", "--target", $site)
    if (-not [string]::IsNullOrWhiteSpace($WheelSource)) {
        $arguments += @("--no-index", "--find-links", $WheelSource)
    } elseif (-not $AllowNetwork) {
        throw "An offline wheelhouse is required (use -Wheelhouse), or explicitly pass -AllowNetwork."
    }
    foreach ($file in $requirements) { $arguments += @("--requirement", $file) }
    $oldTemp = $env:TEMP
    $oldTmp = $env:TMP
    $oldCache = $env:PIP_CACHE_DIR
    try {
        $cache = Join-Path $Work "pip-cache"
        New-Item -ItemType Directory -Path $cache -Force | Out-Null
        $env:TEMP = $Work
        $env:TMP = $Work
        $env:PIP_CACHE_DIR = $cache
        & $builderPython @arguments
        if ($LASTEXITCODE -ne 0) { throw "pip could not install the portable dependencies." }
    } finally {
        $env:TEMP = $oldTemp
        $env:TMP = $oldTmp
        $env:PIP_CACHE_DIR = $oldCache
    }
    $imports = "import fastapi,uvicorn,httpx,yaml,pydantic; print('portable imports OK')"
    $oldNoBytecode = $env:PYTHONDONTWRITEBYTECODE
    try {
        $env:PYTHONDONTWRITEBYTECODE = "1"
        & $PortablePython -I -c $imports
        if ($LASTEXITCODE -ne 0) { throw "The bundled Python cannot import the MedBox dependencies." }
    } finally {
        $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode
    }
}

function Publish-Launcher([string]$Target, [string]$Work) {
    $dotnet = Get-CommandPath "dotnet.exe"
    if ([string]::IsNullOrWhiteSpace($dotnet)) { throw "dotnet SDK is required to publish MedBox.exe." }
    $source = Join-Path $RepoRoot "launcher\MedBox.Launcher"
    $buildSource = Join-Path $Work "launcher-src"
    Copy-CleanTree $source $buildSource @("bin")
    $project = Join-Path $buildSource "MedBox.Launcher.csproj"
    $publish = Join-Path $Work "launcher-publish"
    $nuget = Join-Path $Work "nuget"
    New-Item -ItemType Directory -Path $publish -Force | Out-Null
    New-Item -ItemType Directory -Path $nuget -Force | Out-Null
    $oldTemp = $env:TEMP
    $oldTmp = $env:TMP
    $oldNuget = $env:NUGET_PACKAGES
    try {
        $env:TEMP = $Work
        $env:TMP = $Work
        $env:NUGET_PACKAGES = $nuget
        if ($AllowNetwork) {
            & $dotnet restore $project --runtime win-x64 --packages $nuget
            if ($LASTEXITCODE -ne 0) { throw "dotnet restore failed." }
            $restoreFlag = @("--no-restore")
        } else {
            if (-not (Test-Path -LiteralPath (Join-Path $buildSource "obj\project.assets.json") -PathType Leaf)) {
                throw "Launcher restore assets are absent. Restore once, or explicitly pass -AllowNetwork."
            }
            # project.assets.json records the existing read-only package cache.
            # Build output and all temporary writes still stay under $Work.
            $env:NUGET_PACKAGES = $oldNuget
            $restoreFlag = @("--no-restore")
        }
        $args = @("publish", $project, "--configuration", "Release", "--runtime", "win-x64", "--self-contained", "true", "--output", $publish) + $restoreFlag
        & $dotnet @args
        if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed." }
        # The SDK leaves compiler servers running for minutes, and they keep
        # DLLs inside the work folder open. On a fast disk the build reached
        # cleanup before they exited, and "Access denied" on one of their files
        # reported a finished bundle as a failed build. The bundle does not
        # need them; send them away now.
        & $dotnet build-server shutdown 2>&1 | Out-Null
    } finally {
        $env:TEMP = $oldTemp
        $env:TMP = $oldTmp
        $env:NUGET_PACKAGES = $oldNuget
    }
    $launcher = Join-Path $publish "MedBox.exe"
    if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "dotnet publish did not produce MedBox.exe." }
    foreach ($file in Get-ChildItem -LiteralPath $publish -File) {
        Copy-Item -LiteralPath $file.FullName -Destination (Join-Path $Target $file.Name) -Force
    }
}

function Copy-Documentation([string]$BundleRoot) {
    # The kill moment and the Friday-morning check travel with the bundle:
    # a presenter with only this folder must be able to do both.
    $tools = Join-Path $BundleRoot "tools"
    New-Item -ItemType Directory -Path $tools -Force | Out-Null
    foreach ($script in @("assistant.ps1", "preflight.ps1")) {
        Copy-Item -LiteralPath (Join-Path $RepoRoot "tools\$script") -Destination (Join-Path $tools $script) -Force
    }
    $documentation = Join-Path $BundleRoot "documentation"
    New-Item -ItemType Directory -Path $documentation -Force | Out-Null
    Copy-CleanTree (Join-Path $RepoRoot "docs") $documentation
    Copy-Item -LiteralPath (Join-Path $RepoRoot "README.md") -Destination (Join-Path $documentation "README.md") -Force
    Copy-Item -LiteralPath (Join-Path $RepoRoot "packaging\LISEZ-MOI.txt") -Destination (Join-Path $BundleRoot "LISEZ-MOI.txt") -Force
    # One double-click for the presenter: the machine check, then MedBox.exe.
    Copy-Item -LiteralPath (Join-Path $RepoRoot "packaging\DEMARRER-LA-DEMO.cmd") -Destination (Join-Path $BundleRoot "DEMARRER-LA-DEMO.cmd") -Force
    foreach ($path in $ExtraDocument) {
        $full = [IO.Path]::GetFullPath($path)
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw "Extra document missing: $full" }
        Copy-Item -LiteralPath $full -Destination (Join-Path $documentation ([IO.Path]::GetFileName($full))) -Force
    }
    $licenses = Join-Path $BundleRoot "licenses"
    New-Item -ItemType Directory -Path $licenses -Force | Out-Null
    $projectLicenses = @(Get-ChildItem -LiteralPath $RepoRoot -File | Where-Object { $_.Name -match '^(LICENSE|COPYING|NOTICE)' })
    if ($projectLicenses.Count -eq 0) {
        [IO.File]::WriteAllText(
            (Join-Path $licenses "PROJECT-LICENSE-MISSING.txt"),
            "No project distribution license was present in the source tree at build time.`r`nDo not treat this bundle as cleared for redistribution until the owner supplies one.`r`n",
            (New-Object Text.UTF8Encoding($false)))
    } else {
        foreach ($license in $projectLicenses) {
            Copy-Item -LiteralPath $license.FullName -Destination (Join-Path $licenses $license.Name) -Force
        }
    }
    Copy-Item -LiteralPath (Join-Path $RepoRoot "packaging\THIRD-PARTY-NOTICES.txt") -Destination (Join-Path $licenses "THIRD-PARTY-NOTICES.txt") -Force
}

function Get-GitFact([string[]]$Arguments) {
    $git = Get-CommandPath "git.exe"
    if ([string]::IsNullOrWhiteSpace($git)) { return $null }
    $value = & $git -C $RepoRoot @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return (($value | Out-String).Trim())
}

function Write-BundleManifest([string]$BundleRoot, [bool]$HasOllama, [bool]$HasModel, [bool]$HasSpeech) {
    $manifestFolder = Join-Path $BundleRoot "manifests"
    New-Item -ItemType Directory -Path $manifestFolder -Force | Out-Null
    $commit = Get-GitFact @("rev-parse", "HEAD")
    $branch = Get-GitFact @("branch", "--show-current")
    $dirtyText = Get-GitFact @("status", "--porcelain")
    $model = Get-ConfigValue "ai" "model"
    $requiredOllama = Get-ConfigValue "ai" "required_ollama"
    $manifest = [ordered]@{
        schemaVersion = 1
        product = "MedBox"
        platform = "windows-x64"
        source = [ordered]@{
            commit = $commit
            branch = $branch
            dirty = -not [string]::IsNullOrWhiteSpace($dirtyText)
        }
        components = [ordered]@{
            launcher = "self-contained-dotnet-8"
            python = "portable"
            ollama = [ordered]@{ present = $HasOllama; requiredVersion = $requiredOllama }
            model = [ordered]@{ present = $HasModel; name = $model }
            answerModel = [ordered]@{ name = (Get-ConfigValue "ai" "answer_model") }
            speechModel = [ordered]@{ present = $HasSpeech; name = "faster-whisper-base" }
            voice = [ordered]@{ present = (Test-Path -LiteralPath (Join-Path $RepoRoot "models\piper\fr_FR-siwis-medium.onnx") -PathType Leaf); name = "fr_FR-siwis-medium" }
        }
        readiness = [ordered]@{
            completeForVoiceDemo = ($HasOllama -and $HasModel -and $HasSpeech)
            medicalDevice = $false
            note = "Research and education prototype; not a medical device."
        }
        mutableDirectories = @("data", "logs")
        integrity = [ordered]@{
            algorithm = "SHA-256"
            file = "manifests/SHA256SUMS"
        }
    }
    $json = $manifest | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText((Join-Path $manifestFolder "bundle-manifest.json"), $json + "`n", (New-Object Text.UTF8Encoding($false)))
}

function Write-Checksums([string]$BundleRoot) {
    $manifestFolder = Join-Path $BundleRoot "manifests"
    $sumFile = Join-Path $manifestFolder "SHA256SUMS"
    $lines = @()
    $files = Get-ChildItem -LiteralPath $BundleRoot -Recurse -File | Where-Object {
        $_.FullName -ne $sumFile -and
        -not (Get-RelativePath $BundleRoot $_.FullName).StartsWith("data\", [StringComparison]::OrdinalIgnoreCase) -and
        -not (Get-RelativePath $BundleRoot $_.FullName).StartsWith("logs\", [StringComparison]::OrdinalIgnoreCase)
    } | Sort-Object FullName
    foreach ($file in $files) {
        $relative = (Get-RelativePath $BundleRoot $file.FullName).Replace('\', '/')
        $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $lines += "$hash *$relative"
    }
    [IO.File]::WriteAllLines($sumFile, $lines, (New-Object Text.UTF8Encoding($false)))
}

function Test-Bundle([string]$BundleRoot, [switch]$RunSmoke) {
    Write-Step "Integrity check"
    foreach ($required in @("MedBox.exe", "app\medbox.py", "runtime\python\python.exe", "manifests\bundle-manifest.json", "manifests\SHA256SUMS")) {
        if (-not (Test-Path -LiteralPath (Join-Path $BundleRoot $required) -PathType Leaf)) {
            throw "Bundle is incomplete: $required is missing."
        }
    }
    $sumFile = Join-Path $BundleRoot "manifests\SHA256SUMS"
    $seen = 0
    $expectedPaths = @{}
    foreach ($line in Get-Content -LiteralPath $sumFile) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        if ($line -notmatch '^([0-9a-f]{64}) \*(.+)$') { throw "Invalid checksum line: $line" }
        $expected = $Matches[1]
        $relative = $Matches[2].Replace('/', '\')
        if ($relative.Contains("..")) { throw "Unsafe checksum path: $relative" }
        $file = [IO.Path]::GetFullPath((Join-Path $BundleRoot $relative))
        if (-not $file.StartsWith([IO.Path]::GetFullPath($BundleRoot).TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw "Checksum path escapes the bundle: $relative"
        }
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Checksummed file missing: $relative" }
        $key = $relative.ToLowerInvariant()
        if ($expectedPaths.ContainsKey($key)) { throw "Duplicate checksum path: $relative" }
        $expectedPaths[$key] = $true
        $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -ne $expected) { throw "Checksum mismatch: $relative" }
        $seen += 1
    }
    foreach ($file in Get-ChildItem -LiteralPath $BundleRoot -Recurse -File) {
        $relative = (Get-RelativePath $BundleRoot $file.FullName).Replace('/', '\')
        if ($relative -eq "manifests\SHA256SUMS" -or
            $relative.StartsWith("data\", [StringComparison]::OrdinalIgnoreCase) -or
            $relative.StartsWith("logs\", [StringComparison]::OrdinalIgnoreCase) -or
            $relative -match '(^|\\)__pycache__\\' -or
            $relative.EndsWith(".pyc", [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        if (-not $expectedPaths.ContainsKey($relative.ToLowerInvariant())) {
            throw "Unchecksummed payload file: $relative"
        }
    }
    Write-Host "OK: $seen payload files passed SHA-256."
    $metadata = Get-Content -LiteralPath (Join-Path $BundleRoot "manifests\bundle-manifest.json") -Raw | ConvertFrom-Json
    if (-not $metadata.readiness.completeForVoiceDemo) {
        Add-Warning "bundle integrity is valid, but Ollama/model/speech completeness is false in bundle-manifest.json"
        if ($RequireComplete) { throw "RequireComplete was requested, but the voice demo bundle is incomplete." }
    }
    if (-not $RunSmoke) { return }
    Write-Step "Runtime smoke test"
    $python = Join-Path $BundleRoot "runtime\python\python.exe"
    $entry = Join-Path $BundleRoot "app\medbox.py"
    $oldNoBytecode = $env:PYTHONDONTWRITEBYTECODE
    $oldDatabase = $env:MEDBOX_DATABASE
    try {
        $env:PYTHONDONTWRITEBYTECODE = "1"
        $env:MEDBOX_DATABASE = Join-Path $BundleRoot "data\smoke.db"
        # -s, as the launcher passes it: the embeddable runtime otherwise reads
        # the current user's roaming site-packages, and a bundle that only works
        # on the machine that built it is not portable.
        & $python -s $entry --check
        if ($LASTEXITCODE -ne 0) { throw "medbox.py --check failed in the portable runtime." }
        $isolated = (& $python -s -c "import site, sys; sys.stdout.write('isolated' if not site.ENABLE_USER_SITE and not any('site-packages' in p and 'runtime' not in p.lower() for p in sys.path) else 'leaking')" 2>&1 | Out-String).Trim()
        if ($isolated -ne "isolated") { throw "The portable Python still sees a site-packages outside the bundle ($isolated)." }
    } finally {
        $env:PYTHONDONTWRITEBYTECODE = $oldNoBytecode
        $env:MEDBOX_DATABASE = $oldDatabase
        $smokeDb = Join-Path $BundleRoot "data\smoke.db"
        if (Test-Path -LiteralPath $smokeDb -PathType Leaf) { Remove-Item -LiteralPath $smokeDb -Force }
    }
    $ollama = Join-Path $BundleRoot "runtime\ollama\ollama.exe"
    if (Test-Path -LiteralPath $ollama -PathType Leaf) {
        & $ollama --version
        if ($LASTEXITCODE -ne 0) { throw "Bundled Ollama did not report a version." }
    }
    Write-Host "OK: portable runtime smoke test passed."
}

function Test-FreeSpace([string]$Path, [double]$RequiredGB) {
    $root = [IO.Path]::GetPathRoot($Path)
    if ([string]::IsNullOrWhiteSpace($root)) { return }
    $driveName = $root.TrimEnd('\').TrimEnd(':')
    $drive = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
    if ($null -eq $drive -or $null -eq $drive.Free) { return }
    $freeGB = [math]::Round($drive.Free / 1GB, 2)
    if ($freeGB -lt $RequiredGB) {
        throw "Destination drive $root has $freeGB GB free; at least $RequiredGB GB is required."
    }
    Write-Host "Destination free space: $freeGB GB on $root"
}

function Invoke-Preflight {
    Write-Step "Portable bundle preflight"
    $pythonSource = Get-PythonRuntimeSource
    if ([string]::IsNullOrWhiteSpace($pythonSource) -or -not (Test-Path -LiteralPath $pythonSource)) {
        Add-Blocker "portable Python runtime not supplied; set -PythonRuntime or MEDBOX_PYTHON_RUNTIME"
    } elseif ((Test-Path -LiteralPath $pythonSource -PathType Leaf) -and [string]::IsNullOrWhiteSpace($PythonSha256)) {
        Add-Blocker "Python archive supplied without -PythonSha256"
    } else {
        Write-Host "OK: Python runtime source $pythonSource"
    }
    $wheelSource = Get-WheelhouseSource
    if ([string]::IsNullOrWhiteSpace($wheelSource) -and -not $AllowNetwork) {
        Add-Blocker "offline wheelhouse not supplied; set -Wheelhouse or explicitly pass -AllowNetwork"
    } elseif (-not [string]::IsNullOrWhiteSpace($wheelSource) -and -not (Test-Path -LiteralPath $wheelSource -PathType Container)) {
        Add-Blocker "wheelhouse directory missing: $wheelSource"
    } else {
        $dependencySource = if ($AllowNetwork -and [string]::IsNullOrWhiteSpace($wheelSource)) { "explicit network mode" } else { $wheelSource }
        Write-Host "OK: dependency source $dependencySource"
    }
    if ([string]::IsNullOrWhiteSpace((Get-CommandPath "dotnet.exe"))) {
        Add-Blocker "dotnet SDK not found; required for the self-contained launcher"
    } else {
        Write-Host "OK: dotnet SDK found"
    }
    if (-not $AllowNetwork -and -not (Test-Path -LiteralPath (Join-Path $RepoRoot "launcher\MedBox.Launcher\obj\project.assets.json") -PathType Leaf)) {
        Add-Blocker "offline launcher restore assets are missing; run dotnet restore once or pass -AllowNetwork"
    }
    $ollamaSource = Get-OllamaRuntimeSource
    $hasOllama = Test-OllamaRuntime $ollamaSource
    if ($hasOllama) { Write-Host "OK: Ollama runtime $ollamaSource" }
    $modelName = Get-ConfigValue "ai" "model"
    $modelClosure = Get-OllamaModelClosure (Get-OllamaModelsSource) $modelName
    if ($null -ne $modelClosure) {
        $modelBytes = ($modelClosure.Blobs | Measure-Object Size -Sum).Sum
        Write-Host ("OK: model {0}, verified closure {1:N2} GB" -f $modelName, ($modelBytes / 1GB))
    }
    # The question model (config [ai] answer_model), when it is another one:
    # small, so a spoken question answers in seconds on a processor.
    $answerName = Get-ConfigValue "ai" "answer_model"
    $answerClosure = $null
    if ($answerName -and $answerName -ne $modelName) {
        $answerClosure = Get-OllamaModelClosure (Get-OllamaModelsSource) $answerName
        if ($null -ne $answerClosure) {
            $answerBytes = ($answerClosure.Blobs | Measure-Object Size -Sum).Sum
            Write-Host ("OK: answer model {0}, verified closure {1:N2} GB" -f $answerName, ($answerBytes / 1GB))
        }
    }
    $speechSource = Get-SpeechModelSource
    $hasSpeech = Test-SpeechModel $speechSource
    if ($hasSpeech) { Write-Host "OK: speech model $speechSource" }
    $projectLicense = @(Get-ChildItem -LiteralPath $RepoRoot -File | Where-Object { $_.Name -match '^(LICENSE|COPYING|NOTICE)' })
    if ($projectLicense.Count -eq 0) { Add-Warning "project distribution license is absent; the bundle will carry an explicit redistribution warning" }
    Write-Host "`nPreflight: $($script:Blockers.Count) blocker(s), $($script:Warnings.Count) warning(s)."
    if ($RequireComplete -and (-not $hasOllama -or $null -eq $modelClosure -or -not $hasSpeech)) {
        Add-Blocker "RequireComplete requested, but Ollama, configured model, and speech model are not all present"
    }
    if ($RequireComplete -and $answerName -and $answerName -ne $modelName -and $null -eq $answerClosure) {
        Add-Blocker "RequireComplete requested, but the answer model $answerName is absent from the Ollama store"
    }
    return [pscustomobject]@{
        Python = $pythonSource
        Wheelhouse = $wheelSource
        Ollama = $ollamaSource
        Model = $modelClosure
        AnswerModel = $answerClosure
        Speech = $speechSource
        HasOllama = $hasOllama
        HasSpeech = $hasSpeech
    }
}

try {
    $Destination = Assert-SafeDestination $Destination
    if ($Mode -eq "Check" -or $Mode -eq "Smoke") {
        if (-not (Test-Path -LiteralPath $Destination -PathType Container)) {
            throw "Bundle destination does not exist: $Destination"
        }
        Test-Bundle $Destination -RunSmoke:($Mode -eq "Smoke")
        exit 0
    }

    $inventory = Invoke-Preflight
    if ($Mode -eq "Preflight") {
        if ($script:Blockers.Count -gt 0) { exit 1 }
        exit 0
    }
    if ($script:Blockers.Count -gt 0) {
        throw "Build stopped by preflight blockers."
    }
    if (Test-Path -LiteralPath $Destination) {
        throw "Destination already exists; choose a new explicit folder. Nothing is overwritten: $Destination"
    }
    Test-FreeSpace $Destination $MinimumFreeGB
    $parent = [IO.Path]::GetDirectoryName($Destination)
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $leaf = [IO.Path]::GetFileName($Destination)
    $token = [guid]::NewGuid().ToString("N")
    $stagePrefix = ".$leaf.staging-"
    $workPrefix = ".$leaf.work-"
    $stage = Join-Path $parent ($stagePrefix + $token)
    $work = Join-Path $parent ($workPrefix + $token)
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    New-Item -ItemType Directory -Path $work -Force | Out-Null
    $built = $false
    try {
        Write-Step "Application source"
        Copy-App $stage
        Copy-Documentation $stage
        New-Item -ItemType Directory -Path (Join-Path $stage "data") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $stage "logs") -Force | Out-Null

        Write-Step "Portable Python"
        $pythonTarget = Join-Path $stage "runtime\python"
        Prepare-Python $inventory.Python $PythonSha256 $pythonTarget $work
        Install-PythonDependencies (Join-Path $pythonTarget "python.exe") $pythonTarget $work $inventory.Wheelhouse $inventory.HasSpeech

        Write-Step "Self-contained launcher"
        Publish-Launcher $stage $work

        if ($inventory.HasOllama) {
            Write-Step "CPU-only Ollama runtime"
            Copy-OllamaRuntime $inventory.Ollama (Join-Path $stage "runtime\ollama")
        }
        if ($null -ne $inventory.Model) {
            Write-Step "Configured Ollama model closure"
            Copy-OllamaModel $inventory.Model (Join-Path $stage "models\ollama") (Join-Path $stage "licenses")
        }
        if ($null -ne $inventory.AnswerModel) {
            Write-Step "Answer model closure"
            Copy-OllamaModel $inventory.AnswerModel (Join-Path $stage "models\ollama") (Join-Path $stage "licenses")
        }
        if ($inventory.HasSpeech) {
            Write-Step "Offline speech model"
            Copy-CleanTree $inventory.Speech (Join-Path $stage "app\models\faster-whisper-base")
        }
        # The assistant's voice, when the repository has it. Optional, like the
        # microphone: the station says in /api/status whether it is there.
        $voiceSource = Join-Path $RepoRoot "models\piper"
        if (Test-Path -LiteralPath (Join-Path $voiceSource "fr_FR-siwis-medium.onnx") -PathType Leaf) {
            Write-Step "Offline voice (Piper fr_FR-siwis-medium)"
            Copy-CleanTree $voiceSource (Join-Path $stage "app\models\piper")
        }

        Write-Step "Manifest and checksums"
        Write-BundleManifest $stage $inventory.HasOllama ($null -ne $inventory.Model) $inventory.HasSpeech
        Write-Checksums $stage
        Test-Bundle $stage -RunSmoke
        Move-Item -LiteralPath $stage -Destination $Destination
        $built = $true
        Write-Host "`nPortable bundle ready: $Destination" -ForegroundColor Green
    } finally {
        try {
            Remove-Ephemeral $work $parent $workPrefix
        } catch {
            if (-not $built) { throw }
            # The bundle is whole and verified; a locked temporary file is not
            # a reason to say otherwise.
            Write-Host "`nWARNING: the bundle is complete, but the work folder could not be removed ($($_.Exception.Message)). Delete it by hand: $work" -ForegroundColor Yellow
        }
        if (-not $built) { Remove-Ephemeral $stage $parent $stagePrefix }
    }
    exit 0
} catch {
    Write-Host "`nPORTABLE BUILD FAILED: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
