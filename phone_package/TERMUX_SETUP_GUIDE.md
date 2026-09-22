# 📱 SentinelDR Phone Server - Termux Setup Guide

## 📋 **Prerequisites**

1. **Install Termux** from Google Play Store or F-Droid
2. **Android phone** with internet connectivity (WiFi/Mobile data)
3. **Same network** as your laptop (for local discovery)

## 🚀 **Step 1: Install Python in Termux**

Open Termux and run these commands:

```bash
# Update package list
pkg update && pkg upgrade

# Install Python
pkg install python

# Verify Python version (should be 3.9+)
python --version
```

## 📁 **Step 2: Transfer Phone Server Files**

### Option A: Using GitHub/Git (Recommended)
```bash
# Install git
pkg install git

# Clone your repository
git clone https://github.com/yourusername/sentineldr.git
cd sentineldr/backend
```

### Option B: Manual File Transfer
1. **Zip the phone directory** on your laptop:
   ```powershell
   Compress-Archive -Path "c:\Users\Dharshini\Downloads\sentineldr\backend\phone" -DestinationPath "phone.zip"
   Compress-Archive -Path "c:\Users\Dharshini\Downloads\sentineldr\backend\shared" -DestinationPath "shared.zip"
   ```

2. **Transfer via USB/Cloud/Email** to your phone

3. **Extract in Termux**:
   ```bash
   cd /data/data/com.termux/files/home
   mkdir -p sentineldr/backend
   cd sentineldr/backend
   # Extract your files here
   unzip /storage/emulated/0/Download/phone.zip
   unzip /storage/emulated/0/Download/shared.zip
   ```

## ⚙️ **Step 3: Configure Environment**

Create the configuration file:

```bash
cd ~/sentineldr/backend/phone
cp .env.phone.example .env.phone
```

Edit the configuration:
```bash
# Install a text editor
pkg install nano

# Edit configuration
nano .env.phone
```

**Set these values** in `.env.phone`:
```bash
# MUST match your laptop's API key exactly
API_KEY=my-project-final

# Node identification
NODE_ID=phone-node-02
NODE_ROLE=secondary
NODE_PORT=8001
PEER_PORT=8000

# Database (SQLite - no setup required)
DB_PATH=./sentineldr_phone.db

# Network discovery
DISCOVERY_PORT=47777
DISCOVERY_INTERVAL=5

# Heartbeat monitoring
HEARTBEAT_INTERVAL=3
SYNC_INTERVAL=5
FAILOVER_THRESHOLD=10
```

## 🏃 **Step 4: Run the Phone Server**

```bash
cd ~/sentineldr/backend
export PYTHONPATH="/data/data/com.termux/files/home/sentineldr/backend"
python phone/phone_server.py
```

## 📊 **Step 5: Verify Connection**

You should see logs like:
```
[INFO] Phone node phone-node-02 starting on port 8001
[INFO] Discovery service started on port 47777
[INFO] Heartbeat service started - monitoring laptop
[INFO] Sync service started
[INFO] Failover service started
[INFO] Phone server ready - SentinelDR secondary node active
```

## 🔧 **Step 6: Test from Laptop**

On your laptop, test the phone server:
```bash
# Find your phone's IP address (check in Termux with: ifconfig or ip addr)
curl http://YOUR_PHONE_IP:8001/health
```

## 📱 **Step 7: Keep Running in Background**

### Option A: Termux Background
```bash
# Install wake lock to prevent sleep
pkg install termux-wake-lock

# Acquire wake lock
termux-wake-lock

# Run server
cd ~/sentineldr/backend
export PYTHONPATH="/data/data/com.termux/files/home/sentineldr/backend"
python phone/phone_server.py
```

### Option B: Screen Session
```bash
# Install screen
pkg install screen

# Start screen session
screen -S sentineldr

# Run server in screen
cd ~/sentineldr/backend
export PYTHONPATH="/data/data/com.termux/files/home/sentineldr/backend"
python phone/phone_server.py

# Detach: Ctrl+A, then D
# Reattach later: screen -r sentineldr
```

## 🌐 **Network Configuration**

### Finding Your Phone's IP:
```bash
# In Termux
ifconfig wlan0
# or
ip addr show wlan0
```

### Update Laptop Configuration:
Update your laptop's frontend `.env` file:
```bash
VITE_PHONE_API_URL=http://YOUR_PHONE_IP:8001
```

## 🔒 **Security Notes**

1. **Firewall**: The phone server only listens on port 8001
2. **API Key**: Uses same authentication as laptop server
3. **Network**: Best on trusted WiFi networks
4. **Data**: SQLite database stores minimal operational data only

## 🚨 **Troubleshooting**

### Phone Server Won't Start:
```bash
# Check Python path
echo $PYTHONPATH

# Check file permissions
ls -la phone/phone_server.py

# Run with verbose logging
python phone/phone_server.py --verbose
```

### Can't Connect from Laptop:
1. **Check phone IP**: `ifconfig` in Termux
2. **Test basic connectivity**: `ping YOUR_PHONE_IP` from laptop
3. **Check port**: `netstat -an | grep 8001` in Termux
4. **Firewall**: Ensure port 8001 is accessible

### Discovery Issues:
1. **Same network**: Laptop and phone must be on same WiFi
2. **UDP port**: Ensure port 47777 is not blocked
3. **Router**: Some routers block UDP broadcast

## ⚡ **Performance Tips**

1. **Battery**: Use power saving mode or connect to charger
2. **Network**: Stable WiFi preferred over mobile data
3. **Storage**: Minimal - uses only a few MB
4. **CPU**: Very lightweight - uses minimal resources

## 📈 **Monitoring**

### Check Status via HTTP:
```bash
# Health check
curl http://localhost:8001/health

# Server status  
curl http://localhost:8001/status
```

### View Logs:
The phone server logs to console. Look for:
- `[DISCOVERY]` - Finding laptop server
- `[HEARTBEAT]` - Monitoring laptop health  
- `[SYNC]` - Data synchronization
- `[FAILOVER]` - Disaster recovery events

---

## 🎯 **Quick Start Commands**

```bash
# 1. Setup (one time)
pkg update && pkg install python git nano
git clone YOUR_REPO_URL
cd sentineldr/backend/phone
cp .env.phone.example .env.phone
nano .env.phone  # Set API_KEY=my-project-final

# 2. Run (every time)
cd ~/sentineldr/backend
export PYTHONPATH="/data/data/com.termux/files/home/sentineldr/backend"
termux-wake-lock
python phone/phone_server.py
```

Your SentinelDR disaster recovery system will now run on your Android phone! 📱✅