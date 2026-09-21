import React, { useState, useEffect } from 'react';
import { useHealth } from '../hooks/useHealth.js';
import { useNodes } from '../hooks/useNodes.js';
import { useEvents } from '../hooks/useEvents.js';
import { useSync } from '../hooks/useSync.js';
import { FailoverAlert } from '../components/FailoverAlert.jsx';
import { NodeCard } from '../components/NodeCard.jsx';
import { HealthCard } from '../components/HealthCard.jsx';
import { SyncStatus } from '../components/SyncStatus.jsx';
import { EventFeed } from '../components/EventFeed.jsx';
import { formatUptime, formatRelativeTime } from '../utils/formatters.js';

export default function Dashboard() {
  const { health, phoneHealth, isFailoverActive } = useHealth();
  const { primaryNode, secondaryNode } = useNodes();
  const { events, acknowledge } = useEvents(10);
  const { syncStatus, triggerSync, loading: syncLoading } = useSync();
  const [failoverCount, setFailoverCount] = useState(0);
  const [systemStartTime, setSystemStartTime] = useState(null);

  // Debug logging
  useEffect(() => {
    console.log('📊 Dashboard Data Update:');
    console.log('  Health (Laptop):', health);
    console.log('  Phone Health:', phoneHealth);
    console.log('  Failover Active:', isFailoverActive);
    console.log('  Events count:', events?.length || 0);
    console.log('  Sync Status:', syncStatus);
  }, [health, phoneHealth, isFailoverActive, events, syncStatus]);

  useEffect(() => {
    // Initialize system start time
    if (!systemStartTime) {
      setSystemStartTime(Date.now());
    }
    
    // Count failover events
    const failovers = events.filter(e => e.event_type === 'FAILOVER').length;
    setFailoverCount(failovers);
  }, [events, systemStartTime]);
  
  // Acknowledge all unacknowledged failover/critical events on both nodes
  const handleAcknowledgeFailover = async () => {
    const failoverEvents = events.filter(
      e => !e.acknowledged && (
        e.event_type === 'FAILOVER' || e.severity?.toUpperCase() === 'CRITICAL'
      )
    );
    for (const ev of failoverEvents) {
      if (ev.id) {
        try { await acknowledge(ev.id); } catch (_) { /* best-effort */ }
      }
    }
  };

  // Simulate primary failure for demonstration
  const handleSimulateFailure = async () => {
    if (!confirm('Simulate primary node failure for demonstration?\n\nThis will trigger failover to secondary node.')) {
      return;
    }
    
    try {
      // Call a backend endpoint to simulate failure
      const response = await fetch('/api/simulate-failure', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': import.meta.env.VITE_API_KEY
        }
      });
      
      if (response.ok) {
        alert('Failure simulation initiated. Monitor the dashboard for failover process.');
      }
    } catch (error) {
      console.error('Failed to simulate failure:', error);
      alert('Simulation not available - demo feature only');
    }
  };

  // Calculate system metrics
  const getSystemStatus = () => {
    // Check what we can actually reach
    const primaryReachable = health !== null;
    const secondaryReachable = phoneHealth !== null;
    
    if (isFailoverActive) {
      return { status: 'FAILOVER ACTIVE', color: 'text-sentineldr-warning', icon: '🟡' };
    } else if (primaryReachable && secondaryReachable) {
      return { status: 'OPERATIONAL', color: 'text-sentineldr-success', icon: '🟢' };
    } else if (primaryReachable && !secondaryReachable) {
      return { status: 'PRIMARY ONLY', color: 'text-sentineldr-warning', icon: '🟡' };
    } else if (!primaryReachable && secondaryReachable) {
      return { status: 'SECONDARY ONLY', color: 'text-sentineldr-warning', icon: '🟡' };
    } else {
      return { status: 'DEGRADED', color: 'text-sentineldr-critical', icon: '🔴' };
    }
  };

  const getActiveNode = () => {
    if (isFailoverActive) return 'SECONDARY';
    if (health !== null) return 'PRIMARY';
    if (phoneHealth !== null) return 'SECONDARY';
    return 'UNKNOWN';
  };

  const getLastHeartbeat = () => {
    const healthData = health || phoneHealth;
    if (!healthData?.timestamp) return 'Unknown';
    return formatRelativeTime(healthData.timestamp);
  };

  const getLastSync = () => {
    if (!syncStatus?.last_sync_time) return 'Unknown';
    return formatRelativeTime(syncStatus.last_sync_time);
  };

  const getSystemUptime = () => {
    if (!systemStartTime) return '0s';
    const uptimeSeconds = Math.floor((Date.now() - systemStartTime) / 1000);
    return formatUptime(uptimeSeconds);
  };

  const systemStatus = getSystemStatus();
  
  const getDatabaseHealth = () => {
    // Try laptop health first, then phone health
    const healthData = health || phoneHealth;
    if (!healthData) return { status: 'unknown', subtitle: 'Status unavailable' };
    
    // Health endpoint returns database: "connected" or missing
    const isHealthy = healthData.database === 'connected';
    return {
      status: isHealthy ? 'healthy' : 'error',
      subtitle: isHealthy ? 'PostgreSQL connected' : 'Connection failed'
    };
  };
  
  const getSyncHealth = () => {
    if (!syncStatus) return { status: 'unknown', subtitle: 'Status unavailable' };
    
    const lastSync = syncStatus.last_sync_time;
    const isRecent = lastSync && (Date.now() - new Date(lastSync).getTime()) < 10000; // 10s buffer
    
    return {
      status: isRecent ? 'healthy' : 'warning',
      subtitle: isRecent ? 'Active' : 'Stale sync'
    };
  };
  
  const getHeartbeatHealth = () => {
    // Try laptop health first, then phone health
    const healthData = health || phoneHealth;
    if (!healthData) return { status: 'unknown', subtitle: 'Status unavailable' };
    
    // Health endpoint returns peer_reachable boolean
    const peerReachable = healthData.peer_reachable;
    return {
      status: peerReachable ? 'healthy' : 'warning',
      subtitle: peerReachable ? 'Peer responding' : 'Peer unreachable'
    };
  };
  
  const getFailoverHealth = () => {
    return {
      status: isFailoverActive ? 'critical' : 'healthy',
      subtitle: isFailoverActive ? 'DR mode active' : 'Normal operation'
    };
  };
  
  const databaseHealth = getDatabaseHealth();
  const syncHealth = getSyncHealth();
  const heartbeatHealth = getHeartbeatHealth();
  const failoverHealth = getFailoverHealth();
  
  return (
    <div className="space-y-6">
      {/* Enterprise Header */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className="text-4xl font-bold gradient-text mb-2">
              SentinelDR
            </h1>
            <p className="text-lg text-sentineldr-text-secondary">
              Automated Disaster Recovery & High Availability Platform
            </p>
          </div>
          <div className="text-right">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-2xl">{systemStatus.icon}</span>
              <span className={`text-xl font-bold ${systemStatus.color}`}>
                SYSTEM {systemStatus.status}
              </span>
            </div>
            <div className="text-sm text-sentineldr-text-muted">
              Active Node: {getActiveNode()}
            </div>
          </div>
        </div>

        {/* Node Status Overview */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
          {/* Primary Node Overview */}
          <div className="bg-sentineldr-bg-raised/30 rounded-lg p-4 border border-sentineldr-purple-primary/10">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="text-2xl">💻</span>
                <div>
                  <h3 className="font-semibold text-sentineldr-text-primary">PRIMARY</h3>
                  <div className="text-sm text-sentineldr-text-muted">Laptop Server</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`status-dot ${health ? 'online' : 'offline'}`} />
                <span className={`text-sm font-medium ${
                  health ? 'text-sentineldr-success' : 'text-sentineldr-critical'
                }`}>
                  {health ? 'HEALTHY' : 'OFFLINE'}
                </span>
              </div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">IP Address:</span>
                <span className="font-mono text-sentineldr-text-primary">
                  {primaryNode?.host || health?.local_ip || 'Unknown'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">Port:</span>
                <span className="font-mono text-sentineldr-text-primary">
                  {primaryNode?.port || '8000'}
                </span>
              </div>
            </div>
          </div>

          {/* Secondary Node Overview */}
          <div className="bg-sentineldr-bg-raised/30 rounded-lg p-4 border border-sentineldr-purple-primary/10">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <span className="text-2xl">📱</span>
                <div>
                  <h3 className="font-semibold text-sentineldr-text-primary">SECONDARY</h3>
                  <div className="text-sm text-sentineldr-text-muted">Phone Server</div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span className={`status-dot ${phoneHealth ? 'online' : 'offline'}`} />
                <span className={`text-sm font-medium ${
                  phoneHealth ? 'text-sentineldr-success' : 'text-sentineldr-critical'
                }`}>
                  {phoneHealth ? 'STANDBY' : 'OFFLINE'}
                </span>
              </div>
            </div>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">IP Address:</span>
                <span className="font-mono text-sentineldr-text-primary">
                  {secondaryNode?.host || phoneHealth?.local_ip || 'Unknown'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-sentineldr-text-muted">Port:</span>
                <span className="font-mono text-sentineldr-text-primary">
                  {secondaryNode?.port || '8001'}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Key Metrics Row */}
        <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
          <div className="bg-sentineldr-bg-raised/30 rounded-lg p-3 text-center">
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
              Heartbeat
            </div>
            <div className="font-mono text-lg text-sentineldr-text-primary">
              {getLastHeartbeat()}
            </div>
          </div>

          <div className="bg-sentineldr-bg-raised/30 rounded-lg p-3 text-center">
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
              Last Sync
            </div>
            <div className="font-mono text-lg text-sentineldr-text-primary">
              {getLastSync()}
            </div>
          </div>

          <div className="bg-sentineldr-bg-raised/30 rounded-lg p-3 text-center">
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
              Failovers
            </div>
            <div className="font-mono text-lg text-sentineldr-text-primary">
              {failoverCount}
            </div>
          </div>

          <div className="bg-sentineldr-bg-raised/30 rounded-lg p-3 text-center">
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
              Uptime
            </div>
            <div className="font-mono text-lg text-sentineldr-text-primary">
              {getSystemUptime()}
            </div>
          </div>

          <div className="bg-sentineldr-bg-raised/30 rounded-lg p-3 text-center">
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
              Active Node
            </div>
            <div className="font-mono text-lg text-sentineldr-text-primary">
              {getActiveNode()}
            </div>
          </div>

          <div className="bg-sentineldr-bg-raised/30 rounded-lg p-3 text-center">
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
              System Status
            </div>
            <div className={`font-mono text-lg ${systemStatus.color}`}>
              {systemStatus.status === 'OPERATIONAL' ? 'HEALTHY' : systemStatus.status}
            </div>
          </div>
        </div>

        {/* Demo Button */}
        <div className="mt-4 pt-4 border-t border-sentineldr-purple-primary/20">
          <button
            onClick={handleSimulateFailure}
            className="px-4 py-2 bg-sentineldr-critical/20 border border-sentineldr-critical/30 rounded-lg text-sentineldr-critical font-medium hover:bg-sentineldr-critical/30 transition-colors"
          >
            🔴 Simulate Primary Failure
          </button>
          <span className="ml-3 text-sm text-sentineldr-text-muted">
            (Demo feature for presentation)
          </span>
        </div>
      </div>

      {/* Failover Alert */}
      <FailoverAlert
        isActive={isFailoverActive}
        failoverTime={health?.timestamp}
        onAcknowledge={handleAcknowledgeFailover}
      />

      {/* Node Cards Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <NodeCard node={primaryNode} type="primary" />
        <NodeCard node={secondaryNode} type="secondary" />
      </div>

      {/* Health Cards Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <HealthCard
          title="Database"
          status={databaseHealth.status}
          subtitle={databaseHealth.subtitle}
          icon="💽"
        />
        
        <HealthCard
          title="Sync"
          status={syncHealth.status}
          subtitle={syncHealth.subtitle}
          icon="🔄"
        />
        
        <HealthCard
          title="Heartbeat"
          status={heartbeatHealth.status}
          subtitle={heartbeatHealth.subtitle}
          icon="💓"
        />
        
        <HealthCard
          title="Failover"
          status={failoverHealth.status}
          subtitle={failoverHealth.subtitle}
          icon="🛡️"
        />
      </div>

      {/* Sync Status */}
      <SyncStatus
        syncStatus={syncStatus}
        onTriggerSync={triggerSync}
        loading={syncLoading}
      />

      {/* Recent Events */}
      <EventFeed
        events={events}
        limit={10}
        onAcknowledge={acknowledge}
        className="min-h-[400px]"
      />
    </div>
  );
}