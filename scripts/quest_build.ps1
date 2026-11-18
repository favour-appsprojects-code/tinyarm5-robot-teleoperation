# Build the standalone Quest 3 APK in batch mode (no Unity window needed).
# Usage (repo root, Unity closed):  powershell -ExecutionPolicy Bypass -File scripts\quest_build.ps1
param(
  [string]$Unity = "C:\Program Files\Unity\Hub\Editor\6000.4.8f1\Editor\Unity.exe",
  [switch]$SetupOnly
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$project = Join-Path $root "unity"
$log = Join-Path $root "quest-build.log"
if (-not (Test-Path $Unity)) { throw "Unity not found at $Unity. Install 6000.4.8f1 with Android Build Support, or pass -Unity <path>." }
$method = if ($SetupOnly) { "QuestMRSetup.BatchSetupOnly" } else { "QuestMRSetup.BatchBuild" }
Write-Host "Running $method (log: $log). First run imports packages and can take 10+ minutes..."
$p = Start-Process -FilePath $Unity -Wait -PassThru -NoNewWindow -ArgumentList @(
  "-batchmode", "-quit", "-projectPath", "`"$project`"", "-buildTarget", "Android",
  "-executeMethod", $method, "-logFile", "`"$log`"")
Select-String -Path $log -Pattern "\[TinyARM\]|error CS|Build (Succeeded|Failed)|BuildFailedException" | Select-Object -Last 25 | ForEach-Object { $_.Line }
if ($p.ExitCode -ne 0) { throw "Unity exited with $($p.ExitCode). See $log" }
if (-not $SetupOnly) { Write-Host "APK: $(Join-Path $project 'Builds\TinyARM5-Quest.apk')" }
