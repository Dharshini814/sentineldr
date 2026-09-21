import React, { useState, useEffect } from 'react';
import { useHealth } from '../hooks/useHealth.js';
import { useNodes } from '../hooks/useNodes.js';
import { formatRelativeTime } from '../utils/formatters.js';

export default function Network() {
  const { health, phoneHealth } = useHealth();
  const { primaryNode, secondaryNode } = useNodes();
  const [networkMetrics, setNetworkMetrics] = useState({
    latency: 0,
    packetLoss: 0,
    bandwidth: 0,
    uptime: 0,
    connectionsActive: 0,
    throughput: 0
  });
  const [connectionHistory, setConnectionHistory] = useState([]);

  useEffect(() => {
    // Generate network metrics for demonstration
    const generateMetrics = () => {
      setNetworkMetrics({
        latency: Math.floor(Math.random() * 30) + 15, // 15-45ms
        packetLoss: Math.random() * 0.5, // 0-0.5%
        bandwidth: Math.floor(Math.random() * 50) + 100, // 100-150 Mbps
        uptime: 99.7 + Math.random() * 0.3, // 99.7-100%
        connectionsActive: Math.floor(Math.random() * 20) + 80, // 80-100
        throughput: Math.floor(Math.random() * 1000) + 500 // 500-1500 KB/s
      });
    };

    // Generate connection history
    const generateHistory = () => {
      const history = [];
      const now = Date.now();
      
      for (let i = 0; i < 20; i++) {
        const timestamp = now - (i * 30000); // Every 30 seconds
        const latency = Math.floor(Math.random() * 40) + 10;
        const status = Math.random() > 0.03 ? 'connected' : 'timeout';
        
        history.unshift({
          id: i,
          timestamp,
          latency: status === 'connected' ? latency : null,
          status,
          packetLoss: status === 'connected' ? Math.random() * 0.5 : 100
        });
      }
      
      setConnectionHistory(history);
    };

    generateMetrics();
    generateHistory();

    // Update metrics every 10 seconds
    const interval = setInterval(() => {
      generateMetrics();
      
      // Add new history entry
      setConnectionHistory(prev => {
        const newEntry = {
          id: prev.length,
          timestamp: Date.now(),
          latency: Math.floor(Math.random() * 40) + 10,
          status: Math.random() > 0.03 ? 'connected' : 'timeout',
          packetLoss: Math.random() * 0.5
        };
        
        return [...prev, newEntry].slice(-20);
      });
    }, 10000);

    return () => clearInterval(interval);
  }, []);

  const getConnectionStatus = () => {
    const healthData = health || phoneHealth;
    if (!healthData) {
      return { status: 'UNKNOWN', color: 'text-sentineldr-text-muted', icon: '❓' };
    }
    
    if (primaryNode && secondaryNode) {
      return { status: 'CONNECTED', color: 'text-sentineldr-success', icon: '🟢' };
    } else if (primaryNode || secondaryNode) {
      return { status: 'PARTIAL', color: 'text-sentineldr-warning', icon: '🟡' };
    } else {
      return { status: 'DISCONNECTED', color: 'text-sentineldr-critical', icon: '🔴' };
    }
  };

  const getNetworkQuality = () => {
    if (networkMetrics.latency < 30 && networkMetrics.packetLoss < 0.1) {
      return { quality: 'EXCELLENT', color: 'text-sentineldr-success', icon: '🟢' };
    } else if (networkMetrics.latency < 60 && networkMetrics.packetLoss < 0.5) {
      return { quality: 'GOOD', color: 'text-sentineldr-warning', icon: '🟡' };
    } else {
      return { quality: 'POOR', color: 'text-sentineldr-critical', icon: '🔴' };
    }
  };

  const connectionStatus = getConnectionStatus();
  const networkQuality = getNetworkQuality();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h1 className="text-3xl font-bold gradient-text mb-2">
          🌐 Network Monitoring
        </h1>
        <p className="text-sentineldr-text-secondary">
          Inter-node connectivity and network performance analytics
        </p>
      </div>

      {/* Network Status Overview */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">{connectionStatus.icon}</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Connection</h3>
          </div>
          <div className={`text-2xl font-bold ${connectionStatus.color}`}>
            {connectionStatus.status}
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Node connectivity status
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">{networkQuality.icon}</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Quality</h3>
          </div>
          <div className={`text-2xl font-bold ${networkQuality.color}`}>
            {networkQuality.quality}
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Network performance rating
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">📡</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Latency</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-text-primary">
            {networkMetrics.latency}ms
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Round-trip time
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">📦</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Packet Loss</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-text-primary">
            {networkMetrics.packetLoss.toFixed(2)}%
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Network reliability
          </div>
        </div>
      </div>

      {/* Network Topology */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-xl font-bold text-sentineldr-text-primary mb-6">
          Network Topology
        </h3>
        
        <div className="flex items-center justify-center space-x-12">
          {/* Primary Node */}
          <div className="flex flex-col items-center">
            <div className={`w-32 h-32 rounded-2xl flex flex-col items-center justify-center text-4xl border-4 transition-all ${
              primaryNode?.status === 'healthy' 
                ? 'bg-sentineldr-success/20 border-sentineldr-success/30 shadow-lg shadow-sentineldr-success/20' 
                : 'bg-sentineldr-critical/20 border-sentineldr-critical/30'
            }`}>
              💻
              <div className="mt-2 text-xs font-bold text-sentineldr-text-primary">
                PRIMARY
              </div>
            </div>
            <div className="mt-4 text-center">
              <div className="font-semibold text-sentineldr-text-primary">Laptop Server</div>
              <div className="text-sm text-sentineldr-text-muted">PostgreSQL Database</div>
              <div className="text-xs font-mono text-sentineldr-text-primary mt-1">
                {primaryNode?.host || 'Unknown IP'}:{primaryNode?.port || '8000'}
              </div>
              <div className={`text-xs mt-1 ${primaryNode?.status === 'healthy' ? 'text-sentineldr-success' : 'text-sentineldr-critical'}`}>
                {primaryNode?.status === 'healthy' ? '🟢 Online' : '🔴 Offline'}
              </div>
            </div>
          </div>

          {/* Connection Visualization */}
          <div className="flex flex-col items-center">
            {/* Top connection line */}
            <div className="flex items-center space-x-2">
              <div className={`w-20 h-2 rounded transition-all ${
                connectionStatus.status === 'CONNECTED' ? 'bg-sentineldr-success animate-pulse' : 'bg-sentineldr-text-muted'
              }`} />
              <span className="text-2xl">📡</span>
              <div className={`w-20 h-2 rounded transition-all ${
                connectionStatus.status === 'CONNECTED' ? 'bg-sentineldr-success animate-pulse' : 'bg-sentineldr-text-muted'
              }`} />
            </div>
            
            {/* Connection info */}
            <div className="mt-4 text-center bg-sentineldr-bg-raised rounded-lg p-3">
              <div className="text-sm font-medium text-sentineldr-text-primary mb-1">
                Network Link
              </div>
              <div className="text-xs text-sentineldr-text-muted space-y-1">
                <div>Latency: {networkMetrics.latency}ms</div>
                <div>Loss: {networkMetrics.packetLoss.toFixed(2)}%</div>
                <div>Protocol: HTTP/REST</div>
              </div>
            </div>

            {/* Bottom connection line */}
            <div className="mt-4 flex items-center space-x-2">
              <div className={`w-20 h-2 rounded transition-all ${
                connectionStatus.status === 'CONNECTED' ? 'bg-sentineldr-success animate-pulse' : 'bg-sentineldr-text-muted'
              }`} />
              <span className="text-2xl">🔄</span>
              <div className={`w-20 h-2 rounded transition-all ${
                connectionStatus.status === 'CONNECTED' ? 'bg-sentineldr-success animate-pulse' : 'bg-sentineldr-text-muted'
              }`} />
            </div>
          </div>

          {/* Secondary Node */}
          <div className="flex flex-col items-center">
            <div className={`w-32 h-32 rounded-2xl flex flex-col items-center justify-center text-4xl border-4 transition-all ${
              secondaryNode?.status === 'healthy' 
                ? 'bg-sentineldr-success/20 border-sentineldr-success/30 shadow-lg shadow-sentineldr-success/20' 
                : 'bg-sentineldr-critical/20 border-sentineldr-critical/30'
            }`}>
              📱
              <div className="mt-2 text-xs font-bold text-sentineldr-text-primary">
                SECONDARY
              </div>
            </div>
            <div className="mt-4 text-center">
              <div className="font-semibold text-sentineldr-text-primary">Phone Server</div>
              <div className="text-sm text-sentineldr-text-muted">SQLite Database</div>
              <div className="text-xs font-mono text-sentineldr-text-primary mt-1">
                {secondaryNode?.host || 'Unknown IP'}:{secondaryNode?.port || '8001'}
              </div>
              <div className={`text-xs mt-1 ${secondaryNode?.status === 'healthy' ? 'text-sentineldr-success' : 'text-sentineldr-critical'}`}>
                {secondaryNode?.status === 'healthy' ? '🟢 Ready' : '🔴 Offline'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Network Performance Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <h3 className="text-lg font-bold text-sentineldr-text-primary mb-4">
            Bandwidth Utilization
          </h3>
          <div className="space-y-3">
            <div className="flex justify-between items-center">
              <span className="text-sm text-sentineldr-text-muted">Available:</span>
              <span className="font-mono text-sentineldr-text-primary">{networkMetrics.bandwidth} Mbps</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-sm text-sentineldr-text-muted">Used:</span>
              <span className="font-mono text-sentineldr-text-primary">{Math.floor(networkMetrics.bandwidth * 0.3)} Mbps</span>
            </div>
            <div className="w-full bg-sentineldr-bg-raised rounded-full h-3">
              <div 
                className="h-3 bg-sentineldr-success rounded-full transition-all duration-1000" 
                style={{ width: '30%' }}
              />
            </div>
            <div className="text-xs text-sentineldr-text-muted">30% utilization</div>
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <h3 className="text-lg font-bold text-sentineldr-text-primary mb-4">
            Connection Uptime
          </h3>
          <div className="space-y-3">
            <div className="text-center">
              <div className="text-3xl font-bold text-sentineldr-success">
                {networkMetrics.uptime.toFixed(2)}%
              </div>
              <div className="text-sm text-sentineldr-text-muted">Network uptime</div>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-sentineldr-text-muted">Today:</span>
                <span className="text-sentineldr-success">99.9%</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-sentineldr-text-muted">This week:</span>
                <span className="text-sentineldr-success">99.7%</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-sentineldr-text-muted">This month:</span>
                <span className="text-sentineldr-success">99.5%</span>
              </div>
            </div>
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <h3 className="text-lg font-bold text-sentineldr-text-primary mb-4">
            Active Connections
          </h3>
          <div className="space-y-3">
            <div className="text-center">
              <div className="text-3xl font-bold text-sentineldr-text-primary">
                {networkMetrics.connectionsActive}
              </div>
              <div className="text-sm text-sentineldr-text-muted">Active connections</div>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between text-sm">
                <span className="text-sentineldr-text-muted">HTTP:</span>
                <span className="text-sentineldr-text-primary">{Math.floor(networkMetrics.connectionsActive * 0.8)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-sentineldr-text-muted">WebSocket:</span>
                <span className="text-sentineldr-text-primary">{Math.floor(networkMetrics.connectionsActive * 0.15)}</span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-sentineldr-text-muted">Other:</span>
                <span className="text-sentineldr-text-primary">{Math.floor(networkMetrics.connectionsActive * 0.05)}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Connection History Timeline */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
          Connection Quality Timeline
        </h3>
        
        <div className="bg-sentineldr-bg-raised rounded-lg p-4">
          <div className="flex items-end justify-between h-32">
            {connectionHistory.slice(-10).map((connection, index) => (
              <div key={connection.id} className="flex flex-col items-center gap-2">
                <div 
                  className={`w-6 rounded-t transition-all duration-300 ${
                    connection.status === 'connected' ? 'bg-sentineldr-success' : 'bg-sentineldr-critical'
                  }`}
                  style={{ 
                    height: connection.status === 'connected' ? `${Math.max((connection.latency / 50) * 100, 10)}px` : '4px'
                  }}
                />
                <div className="text-xs text-sentineldr-text-muted">
                  {new Date(connection.timestamp).toLocaleTimeString().slice(-8, -3)}
                </div>
                <div className="text-xs text-sentineldr-text-muted">
                  {connection.status === 'connected' ? `${connection.latency}ms` : 'Lost'}
                </div>
              </div>
            ))}
          </div>
          
          <div className="mt-4 flex justify-between text-sm text-sentineldr-text-muted">
            <span>Latency (ms)</span>
            <span>Last 10 measurements</span>
          </div>
        </div>
      </div>

      {/* Network Configuration */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
          Network Configuration
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="space-y-4">
            <h4 className="font-semibold text-sentineldr-text-primary">Connection Settings</h4>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">Protocol:</span>
                <span className="font-mono text-sentineldr-text-primary">HTTP/1.1</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">Port Range:</span>
                <span className="font-mono text-sentineldr-text-primary">8000-8001</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">Timeout:</span>
                <span className="font-mono text-sentineldr-text-primary">30 seconds</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">Keep-Alive:</span>
                <span className="text-sentineldr-success">Enabled</span>
              </div>
            </div>
          </div>

          <div className="space-y-4">
            <h4 className="font-semibold text-sentineldr-text-primary">Discovery Settings</h4>
            <div className="space-y-2">
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">Auto-Discovery:</span>
                <span className="text-sentineldr-success">Active</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">Broadcast Port:</span>
                <span className="font-mono text-sentineldr-text-primary">47777</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">Discovery Interval:</span>
                <span className="font-mono text-sentineldr-text-primary">10 seconds</span>
              </div>
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">Network Interface:</span>
                <span className="text-sentineldr-text-primary">Wi-Fi</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}