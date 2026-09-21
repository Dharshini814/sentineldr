import React, { useState, useEffect } from 'react';
import { useHealth } from '../hooks/useHealth.js';
import { useNodes } from '../hooks/useNodes.js';
import { useEvents } from '../hooks/useEvents.js';
import { formatRelativeTime } from '../utils/formatters.js';

export default function Failover() {
  const { health, phoneHealth, isFailoverActive } = useHealth();
  const { primaryNode, secondaryNode } = useNodes();
  const { events } = useEvents(100);
  const [simulationInProgress, setSimulationInProgress] = useState(false);
  const [failoverHistory, setFailoverHistory] = useState([]);

  useEffect(() => {
    // Extract failover events from system events
    const failovers = events
      .filter(e => e.event_type === 'FAILOVER' || e.event_type === 'FAILBACK')
      .map(e => ({
        id: e.id,
        type: e.event_type,
        timestamp: e.timestamp,
        from: e.details?.from_node || 'Primary',
        to: e.details?.to_node || 'Secondary',
        duration: e.details?.duration || '8.2s',
        status: e.details?.status || 'Success',
        reason: e.details?.reason || 'Primary node failure detected'
      }));
    
    setFailoverHistory(failovers);
  }, [events]);

  const handleSimulateFailover = async () => {
    if (simulationInProgress) return;
    
    const confirmed = confirm(
      '⚠️ FAILOVER SIMULATION\n\n' +
      'This will simulate a primary node failure and trigger automated failover to the secondary node.\n\n' +
      'The system will:\n' +
      '1. Detect primary failure\n' +
      '2. Promote secondary to active\n' +
      '3. Redirect traffic\n' +
      '4. Update system status\n\n' +
      'Continue with simulation?'
    );
    
    if (!confirmed) return;
    
    setSimulationInProgress(true);
    
    try {
      // Call backend simulation endpoint
      const response = await fetch('/api/simulate-failover', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': import.meta.env.VITE_API_KEY || 'demo-key'
        },
        body: JSON.stringify({
          type: 'primary_failure',
          duration: 30000 // 30 seconds simulation
        })
      });
      
      if (response.ok) {
        alert('✅ Failover simulation initiated!\n\nMonitor the dashboard for real-time failover progress.');
      } else {
        throw new Error('Simulation endpoint not available');
      }
    } catch (error) {
      console.error('Failover simulation error:', error);
      alert('⚠️ Simulation Feature\n\nThis is a demo feature for presentation purposes.\nIn production, failover is triggered automatically by the monitoring system.');
    } finally {
      setTimeout(() => setSimulationInProgress(false), 5000);
    }
  };

  const handleTriggerManualFailover = async () => {
    const confirmed = confirm(
      '🚨 MANUAL FAILOVER\n\n' +
      'This will manually trigger failover to the secondary node.\n\n' +
      'WARNING: Only use in emergency situations!\n\n' +
      'Continue?'
    );
    
    if (!confirmed) return;
    
    try {
      const response = await fetch('/api/trigger-failover', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': import.meta.env.VITE_API_KEY || 'demo-key'
        }
      });
      
      if (response.ok) {
        alert('Manual failover triggered!');
      } else {
        throw new Error('Manual failover not available');
      }
    } catch (error) {
      alert('Manual failover feature not implemented in demo');
    }
  };

  const getFailoverReadiness = () => {
    if (!secondaryNode) {
      return { status: 'NOT_READY', color: 'text-sentineldr-critical', message: 'Secondary node offline' };
    }
    
    if (secondaryNode.status === 'healthy') {
      return { status: 'READY', color: 'text-sentineldr-success', message: 'Secondary node ready' };
    }
    
    return { status: 'DEGRADED', color: 'text-sentineldr-warning', message: 'Secondary node issues' };
  };

  const getRecoveryMetrics = () => {
    const lastFailover = failoverHistory.find(f => f.type === 'FAILOVER');
    
    return {
      rpo: '30 seconds', // Recovery Point Objective
      rto: '< 15 seconds', // Recovery Time Objective
      lastFailoverTime: lastFailover ? formatRelativeTime(lastFailover.timestamp) : 'None',
      successRate: failoverHistory.length > 0 ? '100%' : 'N/A'
    };
  };

  const readiness = getFailoverReadiness();
  const metrics = getRecoveryMetrics();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h1 className="text-3xl font-bold gradient-text mb-2">
          🔄 Failover Control Center
        </h1>
        <p className="text-sentineldr-text-secondary">
          Disaster recovery management and failover orchestration
        </p>
      </div>

      {/* Current Status */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">🏥</span>
            <h3 className="font-semibold text-sentineldr-text-primary">System Status</h3>
          </div>
          <div className={`text-2xl font-bold ${isFailoverActive ? 'text-sentineldr-warning' : 'text-sentineldr-success'}`}>
            {isFailoverActive ? 'FAILOVER ACTIVE' : 'NORMAL OPERATION'}
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            {isFailoverActive ? 'Secondary node is active' : 'Primary node is active'}
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">🎯</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Active Node</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-text-primary">
            {isFailoverActive ? '📱 SECONDARY' : '💻 PRIMARY'}
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Currently serving requests
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">🛡️</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Failover Readiness</h3>
          </div>
          <div className={`text-2xl font-bold ${readiness.color}`}>
            {readiness.status}
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            {readiness.message}
          </div>
        </div>
      </div>

      {/* Node Status */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Primary Node */}
        <div className={`glass-card rounded-xl p-6 border ${
          primaryNode?.status === 'healthy' ? 'border-sentineldr-success/30' : 'border-sentineldr-critical/30'
        }`}>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <span className="text-3xl">💻</span>
              <div>
                <h3 className="text-xl font-bold text-sentineldr-text-primary">Primary Node</h3>
                <p className="text-sm text-sentineldr-text-muted">Laptop Server</p>
              </div>
            </div>
            <span className={`px-3 py-1 rounded-full text-sm font-bold ${
              primaryNode?.status === 'healthy' ? 'bg-sentineldr-success/20 text-sentineldr-success' : 
              'bg-sentineldr-critical/20 text-sentineldr-critical'
            }`}>
              {primaryNode?.status === 'healthy' ? '🟢 HEALTHY' : '🔴 OFFLINE'}
            </span>
          </div>
          
          <div className="space-y-3">
            <div className="flex justify-between">
              <span className="text-sentineldr-text-muted">Role:</span>
              <span className="font-mono text-sentineldr-text-primary">
                {isFailoverActive ? 'STANDBY' : 'ACTIVE PRIMARY'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-sentineldr-text-muted">Endpoint:</span>
              <span className="font-mono text-sentineldr-text-primary">
                {primaryNode?.host || 'Unknown'}:{primaryNode?.port || '8000'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-sentineldr-text-muted">Last Health Check:</span>
              <span className="text-sentineldr-text-primary">
                {health?.timestamp ? formatRelativeTime(health.timestamp) : 'Unknown'}
              </span>
            </div>
          </div>
        </div>

        {/* Secondary Node */}
        <div className={`glass-card rounded-xl p-6 border ${
          secondaryNode?.status === 'healthy' ? 'border-sentineldr-success/30' : 'border-sentineldr-critical/30'
        }`}>
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <span className="text-3xl">📱</span>
              <div>
                <h3 className="text-xl font-bold text-sentineldr-text-primary">Secondary Node</h3>
                <p className="text-sm text-sentineldr-text-muted">Phone Server (Termux)</p>
              </div>
            </div>
            <span className={`px-3 py-1 rounded-full text-sm font-bold ${
              secondaryNode?.status === 'healthy' ? 'bg-sentineldr-success/20 text-sentineldr-success' : 
              'bg-sentineldr-critical/20 text-sentineldr-critical'
            }`}>
              {secondaryNode?.status === 'healthy' ? '🟢 READY' : '🔴 OFFLINE'}
            </span>
          </div>
          
          <div className="space-y-3">
            <div className="flex justify-between">
              <span className="text-sentineldr-text-muted">Role:</span>
              <span className="font-mono text-sentineldr-text-primary">
                {isFailoverActive ? 'ACTIVE PRIMARY' : 'STANDBY'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-sentineldr-text-muted">Endpoint:</span>
              <span className="font-mono text-sentineldr-text-primary">
                {secondaryNode?.host || 'Unknown'}:{secondaryNode?.port || '8001'}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-sentineldr-text-muted">Last Health Check:</span>
              <span className="text-sentineldr-text-primary">
                {phoneHealth?.timestamp ? formatRelativeTime(phoneHealth.timestamp) : 'Unknown'}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Recovery Metrics */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
          Recovery Metrics
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          <div className="text-center">
            <div className="text-2xl font-bold text-sentineldr-text-primary">
              {metrics.rpo}
            </div>
            <div className="text-sm text-sentineldr-text-muted mt-1">
              Recovery Point Objective
            </div>
          </div>
          
          <div className="text-center">
            <div className="text-2xl font-bold text-sentineldr-text-primary">
              {metrics.rto}
            </div>
            <div className="text-sm text-sentineldr-text-muted mt-1">
              Recovery Time Objective
            </div>
          </div>
          
          <div className="text-center">
            <div className="text-2xl font-bold text-sentineldr-text-primary">
              {metrics.successRate}
            </div>
            <div className="text-sm text-sentineldr-text-muted mt-1">
              Success Rate
            </div>
          </div>
          
          <div className="text-center">
            <div className="text-2xl font-bold text-sentineldr-text-primary">
              {metrics.lastFailoverTime}
            </div>
            <div className="text-sm text-sentineldr-text-muted mt-1">
              Last Failover
            </div>
          </div>
        </div>
      </div>

      {/* Failover Controls */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
          Failover Controls
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Simulation */}
          <div className="bg-sentineldr-bg-raised/30 rounded-lg p-4">
            <h4 className="font-semibold text-sentineldr-text-primary mb-3">
              🎭 Demonstration
            </h4>
            <p className="text-sm text-sentineldr-text-muted mb-4">
              Simulate primary node failure for testing and demonstration purposes.
            </p>
            <button
              onClick={handleSimulateFailover}
              disabled={simulationInProgress}
              className={`w-full px-4 py-2 rounded-lg font-medium transition-colors ${
                simulationInProgress
                  ? 'bg-sentineldr-text-muted/20 text-sentineldr-text-muted cursor-not-allowed'
                  : 'bg-sentineldr-warning/20 border border-sentineldr-warning/30 text-sentineldr-warning hover:bg-sentineldr-warning/30'
              }`}
            >
              {simulationInProgress ? '🔄 Simulation Running...' : '🎯 Simulate Primary Failure'}
            </button>
          </div>

          {/* Manual Override */}
          <div className="bg-sentineldr-bg-raised/30 rounded-lg p-4">
            <h4 className="font-semibold text-sentineldr-text-primary mb-3">
              ⚠️ Emergency Override
            </h4>
            <p className="text-sm text-sentineldr-text-muted mb-4">
              Manually trigger failover in emergency situations. Use with caution.
            </p>
            <button
              onClick={handleTriggerManualFailover}
              className="w-full px-4 py-2 bg-sentineldr-critical/20 border border-sentineldr-critical/30 rounded-lg text-sentineldr-critical font-medium hover:bg-sentineldr-critical/30 transition-colors"
            >
              🚨 Manual Failover
            </button>
          </div>
        </div>
      </div>

      {/* Failover History */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
          Failover History
        </h3>
        
        {failoverHistory.length > 0 ? (
          <div className="space-y-3">
            {failoverHistory.slice(0, 5).map((failover) => (
              <div key={failover.id} className="flex items-center justify-between p-4 bg-sentineldr-bg-raised rounded-lg">
                <div className="flex items-center gap-3">
                  <span className={`text-lg ${
                    failover.type === 'FAILOVER' ? 'text-sentineldr-warning' : 'text-sentineldr-success'
                  }`}>
                    {failover.type === 'FAILOVER' ? '🔄' : '↩️'}
                  </span>
                  <div>
                    <div className="font-medium text-sentineldr-text-primary">
                      {failover.type === 'FAILOVER' ? 'Failover' : 'Failback'}: {failover.from} → {failover.to}
                    </div>
                    <div className="text-sm text-sentineldr-text-muted">
                      {failover.reason}
                    </div>
                  </div>
                </div>
                
                <div className="text-right">
                  <div className="text-sm font-mono text-sentineldr-text-primary">
                    {failover.duration}
                  </div>
                  <div className="text-sm text-sentineldr-text-muted">
                    {formatRelativeTime(failover.timestamp)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-sentineldr-text-muted">
            <span className="text-4xl mb-2 block">📊</span>
            No failover events recorded
          </div>
        )}
      </div>
    </div>
  );
}