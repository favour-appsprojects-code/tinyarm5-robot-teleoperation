# Install and launch the APK on a USB-connected Quest 3 (Developer Mode on, USB debugging allowed).
# Optional: -ServerAddress 192.168.1.50 writes teleop_config.json instead of LAN auto-discovery.
param(
  [string]$Adb = "C:\Program Files\Unity\Hub\Editor\6000.4.8f1\Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools\adb.exe",
  [string]$Apk = "",
  [string]$ServerAddress = "",
  [switch]$Logcat
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
if (-not $Apk) { $Apk = Join-Path $root "unity\Builds\TinyARM5-Quest.apk" }
$pkg = "edu.louisville.tinyarm5.teleop"
if (-not (Test-Path $Adb)) { $Adb = "adb" }
& $Adb devices
& $Adb install -r -g "$Apk"
if ($LASTEXITCODE -ne 0) { throw "adb install failed. Is the headset connected and USB debugging allowed inside the headset?" }
if ($ServerAddress) {
  $tmp = Join-Path $env:TEMP "teleop_config.json"
  "{`"serverAddress`": `"$ServerAddress`", `"serverPort`": 5006}" | Set-Content -Encoding ascii $tmp
  & $Adb shell mkdir -p /sdcard/Android/data/$pkg/files
  & $Adb push $tmp /sdcard/Android/data/$pkg/files/teleop_config.json
} else {
  & $Adb shell rm -f /sdcard/Android/data/$pkg/files/teleop_config.json
  Write-Host "No -ServerAddress: the app discovers 'python/server.py --lan' on the LAN."
}
& $Adb shell monkey -p $pkg -c android.intent.category.LAUNCHER 1 | Out-Null
Write-Host "Launched $pkg. Put on the headset; you may now unplug USB."
if ($Logcat) { & $Adb logcat -s Unity:V | Select-String "TinyARM|Exception|OpenXR" }
