# Start the Python IK/MuJoCo backend reachable by the Quest on the local network.
# Run once as Administrator with -AddFirewallRule to allow inbound UDP 5006 on Private networks.
param([switch]$AddFirewallRule, [string]$OutputProfile = "", [switch]$Headless)
$root = Split-Path -Parent $PSScriptRoot
if ($AddFirewallRule) {
  New-NetFirewallRule -DisplayName "TinyARM Python UDP 5006" -Direction Inbound -Protocol UDP -LocalPort 5006 -Action Allow -Profile Private | Out-Null
  Write-Host "Firewall rule added (Private profile). Make sure the Wi-Fi network is set to Private."
}
$serverArgs = @("python\server.py", "--lan", "--port", "5006")
if ($OutputProfile) { $serverArgs += @("--output-profile", $OutputProfile) }
if ($Headless) { $serverArgs += "--headless" }
Set-Location $root
& (Join-Path $root ".venv\Scripts\python.exe") @serverArgs
