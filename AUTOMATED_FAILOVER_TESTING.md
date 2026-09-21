# SentinelDR - Automated Failover/Failback Testing Guide

## 🎯 **Complete Automated Disaster Recovery System**

SentinelDR now provides **TRUE AUTOMATED FAILOVER AND FAILBACK** with zero manual intervention required during disasters.

### **Single Application Endpoint**
- **User Access**: `http://localhost:9000/` (NEVER changes)
- **Automatic Routing**: Smart proxy routes to healthy server
- **Transparent Failover**: User never knows which server is serving

---

## 🚀 **System Startup**

### **Option 1: Automated Startup (Recommended)**
```powershell
cd "c:\Users\Dharshini\Downloads\sentineldr"
.\start_sentineldr.ps1
```

### **Option 2: Manual Startup**
```powershell
# 1. Start Laptop Server (Primary)
cd "c:\Users\Dharshini\Downloads\sentineldr\backend"
uvicorn laptop.main:app --host 0.0.0.0 --port 8000 --reload

# 2. Start Phone Server (Secondary) - NEW WINDOW
cd "c:\Users\Dharshini\Downloads\sentineldr\backend"
$env:PYTHONPATH = "c:\Users\Dharshini\Downloads\sentineldr\backend"
python phone/phone_server.py

# 3. Start Smart Proxy (Automated Router) - NEW WINDOW
cd "c:\Users\Dharshini\Downloads\sentineldr\backend"
python smart_proxy.py

# 4. Start Frontend Dashboard - NEW WINDOW
cd "c:\Users\Dharshini\Downloads\sentineldr\frontend"
npm run dev
```

**⚠️ CRITICAL: Start servers in this exact order for proper discovery.**

---

## 🧪 **Testing Procedures**

### **TEST 1: Normal Operation**

**Goal**: Verify portfolio is served by laptop server during normal operation.

**Steps**:
1. Ensure all services are running
2. Open `http://localhost:9000/` in browser
3. Open `http://localhost:9000/sentineldr-proxy-status` in another tab

**Expected Result**:
- ✅ Portfolio loads successfully
- ✅ Proxy status shows "LAPTOP" as active server
- ✅ Laptop server shows "🔵 ACTIVE"
- ✅ Phone server shows "⭕ STANDBY"

### **TEST 2: Primary Failure (Automated Failover)**

**Goal**: Verify automatic failover when laptop server fails.

**Steps**:
1. With portfolio working normally at `http://localhost:9000/`
2. Go to the laptop server PowerShell window
3. Press **Ctrl+C** to stop the laptop server
4. **DO NOT** change browser URL
5. Wait 10 seconds, then refresh `http://localhost:9000/`
6. Check proxy status page

**Expected Result**:
- ✅ Portfolio remains accessible at same URL
- ✅ Proxy status shows "PHONE" as active server  
- ✅ Phone server shows "🔵 ACTIVE"
- ✅ Laptop server shows "🔴 DOWN"
- ✅ Failover counter increments
- ✅ Console shows: `🚨 AUTOMATIC FAILOVER: Switching from laptop to phone`

### **TEST 3: Application Continuity During Disaster**

**Goal**: Verify portfolio works continuously during laptop outage.

**Steps**:
1. With laptop server stopped (from TEST 2)
2. Navigate portfolio pages at `http://localhost:9000/`
3. Verify all content loads properly
4. Check that phone server is handling requests

**Expected Result**:
- ✅ Portfolio fully functional
- ✅ All portfolio content accessible
- ✅ Phone server request counter increasing
- ✅ No error messages or timeouts

### **TEST 4: Primary Recovery Detection**

**Goal**: Verify system detects when laptop server returns.

**Steps**:
1. With phone serving traffic (from TEST 3)
2. Restart laptop server:
   ```powershell
   cd "c:\Users\Dharshini\Downloads\sentineldr\backend"
   uvicorn laptop.main:app --host 0.0.0.0 --port 8000 --reload
   ```
3. Wait 15 seconds (for health verification)
4. Monitor proxy status page

**Expected Result**:
- ✅ Laptop server status changes to "🟢 HEALTHY"
- ✅ System detects laptop recovery
- ✅ Console shows laptop health checks succeeding

### **TEST 5: Automatic Failback**

**Goal**: Verify automatic failback to laptop when it recovers.

**Steps**:
1. With laptop server restarted and healthy (from TEST 4)
2. Continue refreshing `http://localhost:9000/`
3. Watch proxy status dashboard
4. **DO NOT** change URLs manually

**Expected Result**:
- ✅ Portfolio automatically switches back to laptop
- ✅ Proxy status shows "LAPTOP" as active server
- ✅ Laptop server shows "🔵 ACTIVE" 
- ✅ Phone server returns to "⭕ STANDBY"
- ✅ Recovery counter increments
- ✅ Console shows: `🔄 AUTOMATIC FAILBACK: Switching from phone to laptop`

### **TEST 6: Complete Lifecycle**

**Goal**: Verify the complete automated disaster recovery lifecycle.

**Steps**:
1. Start with normal operation (laptop active)
2. Simulate disaster (stop laptop)
3. Verify failover (phone becomes active)
4. Simulate recovery (restart laptop)
5. Verify failback (laptop becomes active again)
6. **User never changes URL throughout entire process**

**Expected Result**:
- ✅ Portfolio available throughout entire lifecycle
- ✅ Single URL `http://localhost:9000/` works continuously  
- ✅ Automatic state transitions: `LAPTOP → PHONE → LAPTOP`
- ✅ Zero manual intervention required
- ✅ All state changes logged and visible in proxy status

---

## 📊 **Monitoring and Logs**

### **Real-time Monitoring**
- **Proxy Status**: `http://localhost:9000/sentineldr-proxy-status`
  - Server health indicators
  - Active server indicator  
  - Request counters
  - Failover/recovery statistics
  - Auto-refreshes every 3 seconds

### **SentinelDR Dashboard**
- **Dashboard**: `http://localhost:5173/`
  - Node health status
  - Heartbeat monitoring
  - System events
  - Database synchronization

### **Console Logs**
Monitor these critical log messages:

**Normal Operation**:
```
🔀 [1] GET / → LAPTOP
🔀 [2] GET /assets/style.css → LAPTOP
```

**Failover**:
```
🚨 AUTOMATIC FAILOVER: Switching from laptop to phone (laptop down)
🔀 [15] GET / → PHONE
```

**Failback**:
```
🔄 AUTOMATIC FAILBACK: Switching from phone to laptop (healthy)
🔀 [28] GET / → LAPTOP
```

---

## 🔧 **Troubleshooting**

### **Portfolio Not Loading**
1. Check all servers are running: `http://localhost:8000/health` and `http://localhost:8001/health`
2. Check proxy is running: `http://localhost:9000/sentineldr-proxy-status`
3. Verify startup order (laptop first, then phone, then proxy)

### **Failover Not Working**  
1. Verify phone server discovered laptop (check phone logs for discovery messages)
2. Check heartbeat interval (should be every 3 seconds)
3. Ensure laptop is actually stopped (not just unresponsive)

### **Failback Not Working**
1. Wait longer (system requires stable health before failback)
2. Check laptop health endpoint: `http://localhost:8000/health`
3. Verify laptop server fully started and responding

### **Services Not Starting**
1. Check PowerShell execution policy: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
2. Ensure all dependencies installed: `pip install -r requirements-laptop.txt` and `pip install -r requirements-phone.txt`
3. Verify you're in correct directory: `c:\Users\Dharshini\Downloads\sentineldr`

---

## ✅ **Success Criteria**

The implementation is successful when this complete sequence works **automatically**:

1. **NORMAL**: Laptop = PRIMARY, Phone = SECONDARY
2. **DISASTER**: Laptop fails → Phone automatically becomes ACTIVE
3. **CONTINUITY**: Portfolio continues working at same URL
4. **RECOVERY**: Laptop comes back → System detects recovery
5. **FAILBACK**: Traffic automatically returns to Laptop
6. **COMPLETION**: Laptop = PRIMARY, Phone = SECONDARY

**🎯 Zero manual URL changes or server switching required!**

---

## 📝 **Architecture Summary**

```
         USER (always uses localhost:9000)
              ↓
    ┌─────────────────────┐
    │   Smart Proxy       │ ← Automated routing layer
    │   Port: 9000        │
    └──────────┬──────────┘
               │
    ┌──────────┴──────────┐
    │                     │
    ▼                     ▼
┌─────────────┐    ┌─────────────┐
│ LAPTOP      │    │ PHONE       │
│ Primary     │◄──►│ Secondary   │ ← Heartbeat monitoring
│ Port: 8000  │    │ Port: 8001  │   Database sync
└─────────────┘    └─────────────┘   Failover coordination
```

**🛡️ SentinelDR now provides enterprise-grade automated disaster recovery!**