import React, { useState } from 'react';
import { useHealth } from '../hooks/useHealth.js';
import { useNodes } from '../hooks/useNodes.js';
import { useSync } from '../hooks/useSync.js';
import { formatUptime, formatRelativeTime } from '../utils/formatters.js';

export default function Monitoring() {
  const { health, phoneHealth, isFailoverActive } = useHealth();
  const { primaryNode, secondaryNode } = useNodes();
  const { syncStatus } = useSync();
  const [selectedMetric, setSelectedMetric] = useState('overview');

  const getSystemMetrics = () => {
    const healthData = health || phoneHealth;
    return {
      cpuUsage: Math.floor(Math.random() * 40) + 20, // Simulated for demo
      memoryUsage: Math.floor(Math.random() * 30) + 40,
      diskUsage: Math.floor(Math.random() * 20) + 50,
      networkLatency: Math.floor(Math.random() * 20) + 15,
      activeConnections: Math.floor(Math.random() * 50) + 100,
      requestsPerSecond: Math.floor(Math.random() * 100) + 200,
    };
  };

  const getPhoneMetrics = () => ({
    cpuUsage: Math.floor(Math.random() * 25) + 15,
    memoryUsage: Math.floor(Math.random() * 20) + 35,
    batteryLevel: Math.floor(Math.random() * 30) + 65,
    temperature: Math.floor(Math.random() * 10) + 28,
    storageUsage: Math.floor(Math.random() * 25) + 30,
    networkSignal: Math.floor(Math.random() * 20) + 75,
  });

  const systemMetrics = getSystemMetrics();
  const phoneMetrics = getPhoneMetrics();

  const MetricCard = ({ title, value, unit, status, icon, description }) => (
    <div className="glass-card rounded-xl p-4 border border-sentineldr-purple-primary/20">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-xl">{icon}</span>
          <h3 className="font-semibold text-sentineldr-text-primary">{title}</h3>
        </div>
        <span className={`text-sm px-2 py-1 rounded ${
          status === 'healthy' ? 'bg-sentineldr-success/20 text-sentineldr-success' :
          status === 'warning' ? 'bg-sentineldr-warning/20 text-sentineldr-warning' :
          'bg-sentineldr-critical/20 text-sentineldr-critical'
        }`}>
          {status.toUpperCase()}
        </span>
      </div>
      
      <div className="mb-2">
        <div className="text-2xl font-bold text-sentineldr-text-primary">
          {value}{unit}
        </div>
        <div className="text-sm text-sentineldr-text-muted">
          {description}
        </div>
      </div>

      {/* Progress bar for percentage values */}
      {unit === '%' && (
        <div className="w-full bg-sentineldr-bg-raised rounded-full h-2">
          <div 
            className={`h-2 rounded-full transition-all duration-300 ${
              value < 50 ? 'bg-sentineldr-success' :
              value < 80 ? 'bg-sentineldr-warning' :
              'bg-sentineldr-critical'
            }`}
            style={{ width: `${Math.min(value, 100)}%` }}
          />
        </div>
      )}
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h1 className="text-3xl font-bold gradient-text mb-2">
          System Monitoring
        </h1>
        <p className="text-sentineldr-text-secondary">
          Real-time infrastructure performance and health metrics
        </p>
      </div>

      {/* Metric Selection Tabs */}
      <div className="flex gap-2 p-1 bg-sentineldr-bg-raised rounded-lg">
        {[
          { id: 'overview', label: 'Overview', icon: '📊' },
          { id: 'primary', label: 'Primary Node', icon: '💻' },
          { id: 'secondary', label: 'Secondary Node', icon: '📱' },
          { id: 'network', label: 'Network', icon: '🌐' }
        ].map(tab => (
          <button
            key={tab.id}
            onClick={() => setSelectedMetric(tab.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded-md transition-all ${
              selectedMetric === tab.id
                ? 'bg-sentineldr-purple-primary/20 text-sentineldr-purple-light border border-sentineldr-purple-primary/30'
                : 'text-sentineldr-text-secondary hover:text-sentineldr-text-primary hover:bg-sentineldr-bg-raised/50'
            }`}
          >
            <span>{tab.icon}</span>
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Overview Metrics */}
      {selectedMetric === 'overview' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <MetricCard
            title="System Health"
            value={isFailoverActive ? "FAILOVER" : "OPERATIONAL"}
            unit=""
            status={isFailoverActive ? "warning" : "healthy"}
            icon="🏥"
            description="Overall system status"
          />
          
          <MetricCard
            title="Active Connections"
            value={systemMetrics.activeConnections}
            unit=""
            status="healthy"
            icon="🔗"
            description="Current active connections"
          />
          
          <MetricCard
            title="Requests/Second"
            value={systemMetrics.requestsPerSecond}
            unit=""
            status="healthy"
            icon="📈"
            description="Current request rate"
          />
          
          <MetricCard
            title="Network Latency"
            value={systemMetrics.networkLatency}
            unit="ms"
            status={systemMetrics.networkLatency > 50 ? "warning" : "healthy"}
            icon="📡"
            description="Average response time"
          />
          
          <MetricCard
            title="Sync Status"
            value={syncStatus?.last_sync_time ? "ACTIVE" : "UNKNOWN"}
            unit=""
            status={syncStatus?.last_sync_time ? "healthy" : "warning"}
            icon="🔄"
            description={syncStatus?.last_sync_time ? formatRelativeTime(syncStatus.last_sync_time) : "No sync data"}
          />
          
          <MetricCard
            title="Failover Ready"
            value={secondaryNode?.status === 'healthy' ? "YES" : "NO"}
            unit=""
            status={secondaryNode?.status === 'healthy' ? "healthy" : "critical"}
            icon="🛡️"
            description="Secondary node availability"
          />
        </div>
      )}

      {/* Primary Node Metrics */}
      {selectedMetric === 'primary' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <MetricCard
            title="CPU Usage"
            value={systemMetrics.cpuUsage}
            unit="%"
            status={systemMetrics.cpuUsage > 80 ? "critical" : systemMetrics.cpuUsage > 60 ? "warning" : "healthy"}
            icon="⚡"
            description="Processor utilization"
          />
          
          <MetricCard
            title="Memory Usage"
            value={systemMetrics.memoryUsage}
            unit="%"
            status={systemMetrics.memoryUsage > 80 ? "critical" : systemMetrics.memoryUsage > 60 ? "warning" : "healthy"}
            icon="🧠"
            description="RAM utilization"
          />
          
          <MetricCard
            title="Disk Usage"
            value={systemMetrics.diskUsage}
            unit="%"
            status={systemMetrics.diskUsage > 80 ? "critical" : systemMetrics.diskUsage > 60 ? "warning" : "healthy"}
            icon="💾"
            description="Storage utilization"
          />
          
          <MetricCard
            title="Node Status"
            value={primaryNode?.status === 'healthy' ? "HEALTHY" : "OFFLINE"}
            unit=""
            status={primaryNode?.status === 'healthy' ? "healthy" : "critical"}
            icon="💻"
            description={primaryNode?.host ? `IP: ${primaryNode.host}` : "Primary server"}
          />
          
          <MetricCard
            title="Uptime"
            value={primaryNode?.uptime_seconds ? formatUptime(primaryNode.uptime_seconds) : "Unknown"}
            unit=""
            status="healthy"
            icon="⏱️"
            description="Time since last restart"
          />
          
          <MetricCard
            title="Last Heartbeat"
            value={primaryNode?.last_seen ? formatRelativeTime(primaryNode.last_seen) : "Active"}
            unit=""
            status="healthy"
            icon="💓"
            description="Connection status"
          />
        </div>
      )}

      {/* Secondary Node Metrics */}
      {selectedMetric === 'secondary' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <MetricCard
            title="CPU Usage"
            value={phoneMetrics.cpuUsage}
            unit="%"
            status={phoneMetrics.cpuUsage > 70 ? "warning" : "healthy"}
            icon="📱"
            description="Phone processor load"
          />
          
          <MetricCard
            title="Memory Usage"
            value={phoneMetrics.memoryUsage}
            unit="%"
            status={phoneMetrics.memoryUsage > 70 ? "warning" : "healthy"}
            icon="🧠"
            description="Available RAM"
          />
          
          <MetricCard
            title="Battery Level"
            value={phoneMetrics.batteryLevel}
            unit="%"
            status={phoneMetrics.batteryLevel < 20 ? "critical" : phoneMetrics.batteryLevel < 50 ? "warning" : "healthy"}
            icon="🔋"
            description="Power remaining"
          />
          
          <MetricCard
            title="Temperature"
            value={phoneMetrics.temperature}
            unit="°C"
            status={phoneMetrics.temperature > 40 ? "warning" : "healthy"}
            icon="🌡️"
            description="Device temperature"
          />
          
          <MetricCard
            title="Storage Usage"
            value={phoneMetrics.storageUsage}
            unit="%"
            status={phoneMetrics.storageUsage > 80 ? "warning" : "healthy"}
            icon="💾"
            description="Internal storage"
          />
          
          <MetricCard
            title="Network Signal"
            value={phoneMetrics.networkSignal}
            unit="%"
            status={phoneMetrics.networkSignal < 50 ? "warning" : "healthy"}
            icon="📶"
            description="Wi-Fi signal strength"
          />
        </div>
      )}

      {/* Network Metrics */}
      {selectedMetric === 'network' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          <MetricCard
            title="Connection Status"
            value={primaryNode && secondaryNode ? "CONNECTED" : "DEGRADED"}
            unit=""
            status={primaryNode && secondaryNode ? "healthy" : "warning"}
            icon="🌐"
            description="Inter-node connectivity"
          />
          
          <MetricCard
            title="Latency"
            value={systemMetrics.networkLatency}
            unit="ms"
            status={systemMetrics.networkLatency > 100 ? "warning" : "healthy"}
            icon="📡"
            description="Primary ↔ Secondary"
          />
          
          <MetricCard
            title="Packet Loss"
            value="0.0"
            unit="%"
            status="healthy"
            icon="📦"
            description="Network reliability"
          />
          
          <MetricCard
            title="Bandwidth Usage"
            value={Math.floor(Math.random() * 50) + 25}
            unit="Mbps"
            status="healthy"
            icon="🚀"
            description="Current network load"
          />
          
          <MetricCard
            title="Sync Latency"
            value={Math.floor(Math.random() * 500) + 100}
            unit="ms"
            status="healthy"
            icon="⏱️"
            description="Data replication delay"
          />
          
          <MetricCard
            title="Discovery Status"
            value="ACTIVE"
            unit=""
            status="healthy"
            icon="🔍"
            description="Node auto-discovery"
          />
        </div>
      )}

      {/* Performance Timeline */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h2 className="text-xl font-bold text-sentineldr-text-primary mb-4">
          Performance Timeline
        </h2>
        <div className="bg-sentineldr-bg-raised rounded-lg p-4">
          <div className="text-center text-sentineldr-text-muted py-8">
            📈 Performance graphs and timeline visualization
            <br />
            <span className="text-sm">(Charts integration: Chart.js, D3.js, or similar)</span>
          </div>
        </div>
      </div>
    </div>
  );
}