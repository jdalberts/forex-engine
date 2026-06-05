# forex-engine-hold.ps1
# Run ONCE in an elevated PowerShell (right-click PowerShell -> Run as administrator).
# Puts the forex engine project fully on hold: disables every auto-launch task and
# shuts down the running engine + MT5. Reversible later via forex-engine-resume.ps1.
#
# (The 3 autopilot tasks were already disabled from a normal session; this handles
#  the elevation-only tasks plus the live processes.)

$ErrorActionPreference = "Stop"

if (-not (New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())).IsInRole(
    [Security.Principal.WindowsBuiltinRole]::Administrator)) {
    throw "Not elevated. Re-open PowerShell with 'Run as administrator' and re-run this script."
}

Write-Output "=== Disabling auto-launch scheduled tasks ==="
foreach ($t in 'Forex Engine Watchdog','Forex Engine','MT5 AutoStart',
                'Forex Autopilot Morning','Forex Autopilot Evening','Forex Autopilot Weekly') {
    try {
        Disable-ScheduledTask -TaskName $t -ErrorAction Stop | Out-Null
        Write-Output ("  {0,-26} -> {1}" -f $t, (Get-ScheduledTask -TaskName $t).State)
    } catch {
        Write-Output ("  {0,-26} -> SKIP: {1}" -f $t, $_.Exception.Message)
    }
}

Write-Output ""
Write-Output "=== Stopping the running engine process ==="
$engine = Get-CimInstance Win32_Process -Filter "name='python.exe'" |
          Where-Object { $_.CommandLine -match 'engine\.py' }
if ($engine) {
    $engine | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output "  Killed engine PID $($_.ProcessId)" }
} else {
    Write-Output "  (no engine.py process running)"
}

Write-Output ""
Write-Output "=== Stopping MetaTrader 5 ==="
$mt5 = Get-Process terminal64 -ErrorAction SilentlyContinue
if ($mt5) {
    $mt5 | Stop-Process -Force; Write-Output "  Closed MT5 (terminal64 PID $($mt5.Id -join ','))"
} else {
    Write-Output "  (MT5 not running)"
}

Write-Output ""
Write-Output "=== Final state ==="
foreach ($t in 'Forex Engine Watchdog','Forex Engine','MT5 AutoStart',
                'Forex Autopilot Morning','Forex Autopilot Evening','Forex Autopilot Weekly') {
    try { Write-Output ("  {0,-26} {1}" -f $t, (Get-ScheduledTask -TaskName $t).State) } catch {}
}
$stillEngine = Get-CimInstance Win32_Process -Filter "name='python.exe'" | Where-Object { $_.CommandLine -match 'engine\.py' }
$stillMt5 = Get-Process terminal64 -ErrorAction SilentlyContinue
Write-Output ("  engine.py running: {0}" -f [bool]$stillEngine)
Write-Output ("  MT5 running:       {0}" -f [bool]$stillMt5)
Write-Output ""
Write-Output "Project is on hold. To resume later, re-enable the tasks (Enable-ScheduledTask) or ask me to."
