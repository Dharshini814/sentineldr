"""
SentinelDR Smart Proxy - Automated Traffic Router
Provides single application endpoint with automatic failover/failback.
Preserves all existing SentinelDR functionality.
"""

import asyncio
import aiohttp
import json
import time
import logging
from aiohttp import web, ClientTimeout, ClientConnectorError
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

class SentinelDRSmartProxy:
    def __init__(self):
        # Server endpoints
        self.laptop_url = "http://localhost:8000"
        self.phone_url = "http://localhost:8001"
        
        # Health monitoring
        self.health_check_interval = 3  # Match SentinelDR heartbeat interval
        self.laptop_healthy = True
        self.phone_healthy = True
        self.last_laptop_check = 0
        self.last_phone_check = 0
        
        # State tracking
        self.active_server = "laptop"  # laptop | phone
        self.failover_time = None
        self.recovery_time = None
        
        # Statistics
        self.total_requests = 0
        self.laptop_requests = 0
        self.phone_requests = 0
        self.failovers = 0
        self.recoveries = 0
        
    async def check_server_health(self, server_url: str, server_name: str) -> bool:
        """Check if a server is healthy using SentinelDR health endpoint."""
        try:
            timeout = ClientTimeout(total=2)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{server_url}/health") as response:
                    if response.status == 200:
                        health_data = await response.json()
                        # Verify it's actually healthy and the expected server
                        if health_data.get("status") == "healthy":
                            return True
        except Exception as e:
            logger.debug(f"[HEALTH] {server_name} health check failed: {e}")
        return False
    
    async def determine_active_server(self) -> str:
        """Determine which server should be active based on SentinelDR state."""
        current_time = time.time()
        
        # Check laptop health periodically
        if current_time - self.last_laptop_check > self.health_check_interval:
            self.laptop_healthy = await self.check_server_health(self.laptop_url, "laptop")
            self.last_laptop_check = current_time
            
        # Check phone health periodically  
        if current_time - self.last_phone_check > self.health_check_interval:
            self.phone_healthy = await self.check_server_health(self.phone_url, "phone")
            self.last_phone_check = current_time
            
        # Decision logic matching SentinelDR behavior
        if self.laptop_healthy:
            # Laptop is healthy - should be primary
            if self.active_server == "phone":
                # We're failing back to laptop
                self.active_server = "laptop"
                self.recovery_time = current_time
                self.recoveries += 1
                logger.warning(f"🔄 AUTOMATIC FAILBACK: Switching from phone to laptop (healthy)")
            return "laptop"
        elif self.phone_healthy:
            # Laptop is down but phone is healthy - failover to phone
            if self.active_server == "laptop":
                # We're failing over to phone
                self.active_server = "phone"
                self.failover_time = current_time
                self.failovers += 1
                logger.critical(f"🚨 AUTOMATIC FAILOVER: Switching from laptop to phone (laptop down)")
            return "phone"
        else:
            # Both servers down - maintain current active server
            logger.error(f"❌ BOTH SERVERS DOWN: Maintaining {self.active_server} as active")
            return self.active_server
    
    async def get_server_url(self) -> tuple[str, str]:
        """Get the URL and name of the currently active server."""
        active = await self.determine_active_server()
        if active == "laptop":
            return self.laptop_url, "LAPTOP"
        else:
            return self.phone_url, "PHONE"
    
    async def proxy_request(self, request: web.Request) -> web.Response:
        """Proxy request to the active SentinelDR server."""
        try:
            self.total_requests += 1
            
            # Get active server
            server_url, server_name = await self.get_server_url()
            
            # Update request counters
            if server_name == "LAPTOP":
                self.laptop_requests += 1
            else:
                self.phone_requests += 1
            
            # Build target URL
            target_url = f"{server_url}{request.path_qs}"
            
            # Log routing decision
            logger.info(f"🔀 [{self.total_requests}] {request.method} {request.path} → {server_name}")
            
            # Prepare request data
            data = None
            if request.method in ['POST', 'PUT', 'PATCH']:
                data = await request.read()
            
            # Proxy the request
            timeout = ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method=request.method,
                    url=target_url,
                    headers={k: v for k, v in request.headers.items() 
                            if k.lower() not in ['host', 'content-length']},
                    data=data
                ) as response:
                    # Get response content
                    content = await response.read()
                    
                    # Create proxy response
                    proxy_response = web.Response(
                        body=content,
                        status=response.status,
                        headers={k: v for k, v in response.headers.items() 
                                if k.lower() not in ['content-length']}
                    )
                    
                    return proxy_response
                    
        except ClientConnectorError as e:
            logger.error(f"❌ Connection failed to {server_name}: {e}")
            
            # If current server failed, try the other one
            if server_name == "LAPTOP" and self.phone_healthy:
                logger.info("🔄 Trying phone server as fallback...")
                try:
                    fallback_url = f"{self.phone_url}{request.path_qs}"
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.request(
                            method=request.method,
                            url=fallback_url,
                            headers={k: v for k, v in request.headers.items() 
                                    if k.lower() not in ['host', 'content-length']},
                            data=data
                        ) as response:
                            content = await response.read()
                            self.phone_requests += 1
                            return web.Response(
                                body=content,
                                status=response.status,
                                headers={k: v for k, v in response.headers.items() 
                                        if k.lower() not in ['content-length']}
                            )
                except Exception as fallback_error:
                    logger.error(f"❌ Fallback to phone also failed: {fallback_error}")
            
            elif server_name == "PHONE" and self.laptop_healthy:
                logger.info("🔄 Trying laptop server as fallback...")
                try:
                    fallback_url = f"{self.laptop_url}{request.path_qs}"
                    async with aiohttp.ClientSession(timeout=timeout) as session:
                        async with session.request(
                            method=request.method,
                            url=fallback_url,
                            headers={k: v for k, v in request.headers.items() 
                                    if k.lower() not in ['host', 'content-length']},
                            data=data
                        ) as response:
                            content = await response.read()
                            self.laptop_requests += 1
                            return web.Response(
                                body=content,
                                status=response.status,
                                headers={k: v for k, v in response.headers.items() 
                                        if k.lower() not in ['content-length']}
                            )
                except Exception as fallback_error:
                    logger.error(f"❌ Fallback to laptop also failed: {fallback_error}")
            
            # All servers failed
            return web.Response(
                text=self._generate_error_page(),
                status=503,
                content_type="text/html"
            )
            
        except Exception as e:
            logger.error(f"❌ Proxy error: {e}")
            return web.Response(
                text="🚨 SentinelDR: Internal proxy error occurred.",
                status=500,
                content_type="text/html"
            )
    
    def _generate_error_page(self) -> str:
        """Generate error page when all servers are down."""
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>SentinelDR - Service Unavailable</title>
            <style>
                body {{ font-family: Arial, sans-serif; padding: 40px; text-align: center; background: #f5f5f5; }}
                .error {{ background: white; padding: 40px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); max-width: 600px; margin: 0 auto; }}
                .status {{ color: #dc3545; font-size: 1.2em; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="error">
                <h1>🚨 SentinelDR - Service Unavailable</h1>
                <div class="status">All disaster recovery servers are currently unavailable.</div>
                <p>The SentinelDR system is experiencing issues with both primary and secondary servers.</p>
                <p>Please try again in a few moments or contact your system administrator.</p>
                <p><small>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</small></p>
            </div>
        </body>
        </html>
        """
    
    async def proxy_status(self, request: web.Request) -> web.Response:
        """Provide SentinelDR proxy status dashboard."""
        
        # Get current server states
        laptop_state = "🟢 HEALTHY" if self.laptop_healthy else "🔴 DOWN"
        phone_state = "🟢 HEALTHY" if self.phone_healthy else "🔴 DOWN"
        active_indicator = "🔵 ACTIVE" if self.active_server == "laptop" else "⭕ STANDBY"
        phone_indicator = "🔵 ACTIVE" if self.active_server == "phone" else "⭕ STANDBY"
        
        # Calculate uptime
        uptime = time.time() - (self.failover_time or self.recovery_time or time.time())
        uptime_str = f"{int(uptime//60):02d}:{int(uptime%60):02d}"
        
        status_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>SentinelDR Smart Proxy - Status</title>
            <meta http-equiv="refresh" content="3">
            <style>
                body {{ font-family: Arial, sans-serif; padding: 20px; background: #f5f5f5; }}
                .dashboard {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .server-row {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 20px; margin: 15px 0; padding: 15px; background: #f9f9f9; border-radius: 5px; }}
                .metric {{ text-align: center; }}
                .active {{ background: #e7f3ff; border-left: 4px solid #007bff; }}
                .standby {{ background: #f8f9fa; }}
                .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 20px; margin-top: 20px; }}
                .stat-box {{ background: #f8f9fa; padding: 15px; border-radius: 5px; text-align: center; }}
                .healthy {{ color: #28a745; }}
                .down {{ color: #dc3545; }}
                .warning {{ color: #ffc107; }}
            </style>
        </head>
        <body>
            <div class="dashboard">
                <h1>🛡️ SentinelDR Smart Proxy Status</h1>
                <p><strong>Single Application Endpoint:</strong> <a href="/">http://localhost:9000/</a></p>
                <p><strong>Current Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | <strong>Active Server:</strong> {self.active_server.upper()}</p>
                
                <h2>📊 Server Status</h2>
                <div class="server-row {'active' if self.active_server == 'laptop' else 'standby'}">
                    <div class="metric"><strong>Laptop Server</strong><br>{laptop_state}<br>{active_indicator}</div>
                    <div class="metric"><strong>Port:</strong> 8000</div>
                    <div class="metric"><strong>Role:</strong> Primary</div>
                    <div class="metric"><strong>Requests:</strong> {self.laptop_requests}</div>
                </div>
                
                <div class="server-row {'active' if self.active_server == 'phone' else 'standby'}">
                    <div class="metric"><strong>Phone Server</strong><br>{phone_state}<br>{phone_indicator}</div>
                    <div class="metric"><strong>Port:</strong> 8001</div>
                    <div class="metric"><strong>Role:</strong> Secondary</div>
                    <div class="metric"><strong>Requests:</strong> {self.phone_requests}</div>
                </div>
                
                <div class="stats">
                    <div class="stat-box">
                        <h3>Total Requests</h3>
                        <div style="font-size: 1.5em;">{self.total_requests}</div>
                    </div>
                    <div class="stat-box">
                        <h3>Failovers</h3>
                        <div style="font-size: 1.5em; color: #dc3545;">{self.failovers}</div>
                    </div>
                    <div class="stat-box">
                        <h3>Recoveries</h3>
                        <div style="font-size: 1.5em; color: #28a745;">{self.recoveries}</div>
                    </div>
                    <div class="stat-box">
                        <h3>Active Uptime</h3>
                        <div style="font-size: 1.5em;">{uptime_str}</div>
                    </div>
                </div>
                
                <h2>🔗 Access Points</h2>
                <ul>
                    <li><a href="/" target="_blank">Portfolio Application (Auto-Failover)</a></li>
                    <li><a href="http://localhost:5173/" target="_blank">SentinelDR Dashboard</a></li>
                    <li><a href="http://localhost:8000/health" target="_blank">Laptop Health</a></li>
                    <li><a href="http://localhost:8001/health" target="_blank">Phone Health</a></li>
                </ul>
                
                <p><em>Auto-refreshes every 3 seconds | Proxy checks server health every {self.health_check_interval} seconds</em></p>
            </div>
        </body>
        </html>
        """
        
        return web.Response(text=status_html, content_type="text/html")

# Global proxy instance
smart_proxy = SentinelDRSmartProxy()

async def handle_all_requests(request: web.Request) -> web.Response:
    """Route all requests through the smart proxy."""
    return await smart_proxy.proxy_request(request)

async def handle_proxy_status(request: web.Request) -> web.Response:
    """Show proxy status dashboard."""
    return await smart_proxy.proxy_status(request)

def create_app() -> web.Application:
    """Create the smart proxy web application."""
    app = web.Application()
    
    # Special proxy status endpoint
    app.router.add_get('/sentineldr-proxy-status', handle_proxy_status)
    
    # Route all other requests to active server
    app.router.add_route('*', '/{path:.*}', handle_all_requests)
    
    return app

async def main():
    """Start the SentinelDR Smart Proxy."""
    app = create_app()
    
    print("╔════════════════════════════════════════════════╗")
    print("║         SentinelDR Smart Proxy v1.0           ║")
    print("╠════════════════════════════════════════════════╣")
    print("║  Single Application Endpoint: localhost:9000  ║")
    print("║  Primary Server:  localhost:8000 (laptop)     ║")
    print("║  Secondary Server: localhost:8001 (phone)     ║")
    print("║  Health Checks: Every 3 seconds               ║")
    print("╚════════════════════════════════════════════════╝")
    print()
    print("🌐 Portfolio Access: http://localhost:9000/")
    print("📊 Proxy Status:     http://localhost:9000/sentineldr-proxy-status")
    print("🎯 Automated failover/failback is now ACTIVE!")
    print("   - Laptop healthy → Routes to laptop:8000")
    print("   - Laptop down    → Routes to phone:8001") 
    print("   - Laptop recovers → Routes back to laptop:8000")
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', 9000)
    await site.start()
    
    logger.info("🚀 SentinelDR Smart Proxy started on http://localhost:9000/")
    
    # Keep running
    try:
        await asyncio.Future()  # Run forever
    except KeyboardInterrupt:
        logger.info("🛑 Smart Proxy stopped")

if __name__ == '__main__':
    asyncio.run(main())