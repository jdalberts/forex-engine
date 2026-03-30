# Contabo Windows VPS Setup Guide

## Step 1: Connect via Remote Desktop
1. Open **Remote Desktop Connection** on your PC (Win+R → `mstsc`)
2. Enter the IP address from Contabo email
3. Username: `Administrator`
4. Password: from Contabo email
5. Click Connect

## Step 2: Install Python
1. Open Edge browser on VPS
2. Go to https://www.python.org/downloads/
3. Download Python 3.11.x (64-bit)
4. Run installer — **CHECK "Add Python to PATH"**
5. Click "Install Now"
6. Verify: open PowerShell → `python --version`

## Step 3: Install Git
1. Go to https://git-scm.com/download/win
2. Download and install (default options are fine)
3. Verify: open PowerShell → `git --version`

## Step 4: Install MetaTrader 5
1. Go to https://www.metatrader5.com/en/download
2. Download and install MT5
3. Open MT5 → File → Login to Trade Account
4. Server: Pepperstone-Demo
5. Login: your MT5 login from .env
6. Password: your MT5 password from .env
7. **Enable AutoTrading** (button in toolbar — must be green)
8. **Tools → Options → Expert Advisors → Check "Allow algorithmic trading"**
9. Leave MT5 running (minimize, don't close)

## Step 5: Clone the Repo
Open PowerShell on VPS:
```powershell
cd C:\
git clone https://github.com/jdalberts/forex-engine.git
cd forex-engine
pip install -r requirements.txt
```

## Step 6: Configure Environment
```powershell
# Copy your .env file (or create it manually)
notepad C:\forex-engine\.env
```

Paste your .env contents (MT5 login, Telegram tokens, etc.)

## Step 7: Test the Engine
```powershell
cd C:\forex-engine
python engine.py --live
```
Watch for a few cycles — should authenticate, fetch data, evaluate signals.
Ctrl+C to stop once confirmed working.

## Step 8: Set Up Auto-Start (Task Scheduler)

### Task 1: Auto-start MT5
1. Open Task Scheduler (Win+R → `taskschd.msc`)
2. Create Task → Name: "MT5 AutoStart"
3. Trigger: At startup
4. Action: Start a program → Browse to MT5 terminal64.exe
5. Check "Run whether user is logged on or not"
6. OK

### Task 2: Auto-start Engine
1. Create Task → Name: "Forex Engine"
2. Trigger: At startup, delay 30 seconds (let MT5 start first)
3. Action: Start a program
   - Program: `python`
   - Arguments: `C:\forex-engine\engine.py --live`
   - Start in: `C:\forex-engine`
4. Check "Run whether user is logged on or not"
5. Check "Restart the task if it fails" → every 1 minute, up to 5 times
6. OK

## Step 9: Open Dashboard Port
```powershell
# Allow port 8080 through Windows Firewall
netsh advfirewall firewall add rule name="Dashboard" dir=in action=allow protocol=tcp localport=8080
```
Dashboard accessible at: `http://YOUR_VPS_IP:8080`

## Step 10: Test Auto-Restart
1. Reboot the VPS: `shutdown /r /t 0`
2. Wait 2 minutes, reconnect via Remote Desktop
3. Verify MT5 is running and AutoTrading is green
4. Verify engine is running (check logs/engine.log)
5. Verify dashboard at http://YOUR_VPS_IP:8080

## Deploying Updates
From your local PC:
```powershell
python deploy.py
```
This pushes to GitHub, SSHs into VPS, pulls changes, and restarts the engine.
