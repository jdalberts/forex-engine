# forex-engine-resume.ps1
# Run in an elevated PowerShell (right-click PowerShell -> Run as administrator).
# Reverses the on-hold state: re-enables every auto-launch task and starts MT5 + engine.
# See deploy/PROJECT_ON_HOLD.md for context.

$ErrorActionPreference = "Stop"

if (-not (New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole(
    [Security.Principal.WindowsBuiltinRole]::Administrator)) {
    throw "Not elevated. Re-open PowerShell with 'Run as administrator' and re-run this script."
}

Write-Output "=== Re-enabling scheduled tasks ==="
foreach ($t in 'Forex Engine Watchdog','Forex Engine','MT5 AutoStart',
                'Forex Autopilot Morning','Forex Autopilot Evening','Forex Autopilot Weekly') {
    try {
        Enable-ScheduledTask -TaskName $t -ErrorAction Stop | Out-Null
        Write-Output ("  {0,-26} -> {1}" -f $t, (Get-ScheduledTask -TaskName $t).State)
    } catch {
        Write-Output ("  {0,-26} -> SKIP: {1}" -f $t, $_.Exception.Message)
    }
}

Write-Output ""
Write-Output "=== Launching MT5 ==="
Start-ScheduledTask -TaskName 'MT5 AutoStart'
Start-Sleep -Seconds 20
$mt5 = Get-Process terminal64 -ErrorAction SilentlyContinue
Write-Output ("  MT5 running: {0} (PID {1})" -f [bool]$mt5, ($mt5.Id -join ','))

Write-Output ""
Write-Output "=== Launching engine ==="
Start-ScheduledTask -TaskName 'Forex Engine'
Start-Sleep -Seconds 45
$engine = Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -match 'engine\.py' }
Write-Output ("  engine.py running: {0} (PID {1})" -f [bool]$engine, ($engine.ProcessId -join ','))

Write-Output ""
Write-Output "=== Last 8 engine.log lines ==="
Get-Content C:\forex-engine\logs\engine.log -Tail 8

Write-Output ""
Write-Output "If you see 'Broker authentication failed' / 'Invalid account', the Pepperstone"
Write-Output "MT5 demo likely expired — create a new MT5 demo and update .env (see PROJECT_ON_HOLD.md)."
