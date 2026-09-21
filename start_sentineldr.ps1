# SentinelDR Complete System Startup Script
# Starts all components in correct order for automated failover/failback

Write-Host "╔════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║         SentinelDR System Startup             ║" -ForegroundColor Cyan
Write-Host "╚════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Check if in correct directory
$expectedPath = "c:\Users\Dharshini\Downloads\sentineldr"
if ((Get-Location).Path -ne $expectedPath) {
    Write-Host "⚠️  Changing to SentinelDR directory..." -ForegroundColor Yellow
    Set-Location $expectedPath
}

# Function to start a service in a new PowerShell window
function Start-Service {
    param(
        [string]$ServiceName,
        [string]$Command,
        [string]$WorkingDirectory
    )
    
    Write-Host "🚀 Starting $ServiceName..." -ForegroundColor Green
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$WorkingDirectory'; Write-Host '=== $ServiceName ===' -ForegroundColor Magenta; $Command" -WindowStyle Normal
    Start-Sleep 3  # Wait for service to initialize
}

# 1. Start Laptop Server (Primary)
Write-Host "1️⃣  Starting Primary Server (Laptop)..." -ForegroundColor Cyan
Start-Service -ServiceName "Laptop Primary Server" -Command "uvicorn laptop.main:app --host 0.0.0.0 --port 8000 --reload" -WorkingDirectory "c:\Users\Dharshini\Downloads\sentineldr\backend"

# Wait for laptop server to fully start
Write-Host "   ⏳ Waiting for laptop server initialization..." -ForegroundColor Yellow
Start-Sleep 8

# 2. Start Phone Server (Secondary)  
Write-Host "2️⃣  Starting Secondary Server (Phone)..." -ForegroundColor Cyan
Start-Service -ServiceName "Phone Secondary Server" -Command "`$env:PYTHONPATH = 'c:\Users\Dharshini\Downloads\sentineldr\backend'; python phone/phone_server.py" -WorkingDirectory "c:\Users\Dharshini\Downloads\sentineldr\backend"

# Wait for phone server to discover laptop
Write-Host "   ⏳ Waiting for peer discovery and heartbeat establishment..." -ForegroundColor Yellow
Start-Sleep 10

# 3. Start Smart Proxy (Automated Router)
Write-Host "3️⃣  Starting Smart Proxy (Automated Router)..." -ForegroundColor Cyan
Start-Service -ServiceName "SentinelDR Smart Proxy" -Command "python smart_proxy.py" -WorkingDirectory "c:\Users\Dharshini\Downloads\sentineldr\backend"

# Wait for proxy initialization
Write-Host "   ⏳ Waiting for smart proxy initialization..." -ForegroundColor Yellow
Start-Sleep 5

# 4. Start Frontend Dashboard
Write-Host "4️⃣  Starting Frontend Dashboard..." -ForegroundColor Cyan
Start-Service -ServiceName "SentinelDR Dashboard" -Command "npm run dev" -WorkingDirectory "c:\Users\Dharshini\Downloads\sentineldr\frontend"

# Wait for frontend to start
Write-Host "   ⏳ Waiting for frontend startup..." -ForegroundColor Yellow
Start-Sleep 8

# Final status
Write-Host ""
Write-Host "✅ SentinelDR System Startup Complete!" -ForegroundColor Green
Write-Host ""
Write-Host "📊 Access Points:" -ForegroundColor Yellow
Write-Host "   🌐 Portfolio (Auto-Failover): http://localhost:9000/" -ForegroundColor White
Write-Host "   📈 Proxy Status Dashboard:    http://localhost:9000/sentineldr-proxy-status" -ForegroundColor White  
Write-Host "   🎛️  SentinelDR Dashboard:      http://localhost:5173/" -ForegroundColor White
Write-Host ""
Write-Host "🔧 Direct Server Access (for testing):" -ForegroundColor Yellow
Write-Host "   🖥️  Laptop Server Health:     http://localhost:8000/health" -ForegroundColor Gray
Write-Host "   📱 Phone Server Health:       http://localhost:8001/health" -ForegroundColor Gray
Write-Host ""
Write-Host "🎯 Automated Disaster Recovery is now ACTIVE!" -ForegroundColor Magenta
Write-Host "   • Normal operation: Portfolio served by laptop:8000" -ForegroundColor White
Write-Host "   • Laptop failure:   Automatic failover to phone:8001" -ForegroundColor White
Write-Host "   • Laptop recovery:  Automatic failback to laptop:8000" -ForegroundColor White
Write-Host "   • User always uses: http://localhost:9000/ (never changes)" -ForegroundColor Green
Write-Host ""
Write-Host "⚡ Testing:" -ForegroundColor Yellow
Write-Host "   1. Open http://localhost:9000/ (should work normally)" -ForegroundColor White
Write-Host "   2. Stop laptop server (Ctrl+C in laptop window)" -ForegroundColor White
Write-Host "   3. Refresh http://localhost:9000/ (should still work via phone)" -ForegroundColor White
Write-Host "   4. Restart laptop server" -ForegroundColor White
Write-Host "   5. Refresh http://localhost:9000/ (should failback to laptop)" -ForegroundColor White
Write-Host ""

# Open the applications
Write-Host "🌐 Opening applications in browser..." -ForegroundColor Cyan
Start-Sleep 2
Start-Process "http://localhost:9000/"
Start-Sleep 1
Start-Process "http://localhost:9000/sentineldr-proxy-status"
Start-Sleep 1
Start-Process "http://localhost:5173/"

Write-Host "🎉 All applications opened! System ready for demonstration." -ForegroundColor Green