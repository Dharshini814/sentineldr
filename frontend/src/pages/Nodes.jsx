import React from 'react';
import { useHealth } from '../hooks/useHealth.js';
import { useNodes } from '../hooks/useNodes.js';
import { NodeCard } from '../components/NodeCard.jsx';
import { formatUptime, formatRelativeTime, formatChecksum } from '../utils/formatters.js';

export default function Nodes() {
  const { health, status, loading: healthLoading } = useHealth();
  const { primaryNode, secondaryNode, loading: nodesLoading } = useNodes();
  
  const loading = healthLoading || nodesLoading;
  
  if (loading && !health && !primaryNode && !secondaryNode) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-sentineldr-purple-primary border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <div className="text-sentineldr-text-secondary">Loading node information...</div>
        </div>
      </div>
    );
  }
  
  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-sentineldr-text-primary mb-2">
          Nodes
        </h1>
        <p className="text-sentineldr-text-secondary">
          Detailed information about all SentinelDR nodes
        </p>
      </div>
      
      {/* Node Cards */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <NodeCard node={primaryNode} type="primary" />
        <NodeCard node={secondaryNode} type="secondary" />
      </div>
      
      {/* Detailed Node Information */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Primary Node Details */}
        <NodeDetailsCard
          title="Primary Node Details"
          node={primaryNode}
          health={health}
          status={status}
          icon="💻"
        />
        
        {/* Secondary Node Details */}
        <NodeDetailsCard
          title="Secondary Node Details"
          node={secondaryNode}
          health={health}
          icon="📱"
        />
      </div>
      
      {/* Network Discovery Information */}
      <div className="glass-card rounded-xl p-6">
        <h3 className="text-lg font-semibold text-sentineldr-text-primary mb-4 flex items-center gap-2">
          <span>📡</span>
          Network Discovery
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div>
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-2">
              Discovery Protocol
            </div>
            <div className="text-sm text-sentineldr-text-primary mb-1">UDP Broadcast</div>
            <div className="text-xs text-sentineldr-text-secondary">Port 47777</div>
          </div>
          
          <div>
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-2">
              Discovery Interval
            </div>
            <div className="text-sm text-sentineldr-text-primary mb-1">5 seconds</div>
            <div className="text-xs text-sentineldr-text-secondary">Automatic peer detection</div>
          </div>
          
          <div>
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-2">
              IP Configuration
            </div>
            <div className="text-sm text-sentineldr-text-primary mb-1">Automatic</div>
            <div className="text-xs text-sentineldr-text-secondary">No manual setup required</div>
          </div>
        </div>
        
        <div className="mt-6 p-4 bg-sentineldr-info/10 border border-sentineldr-info/30 rounded-lg">
          <div className="flex items-start gap-2">
            <span className="text-sentineldr-info">ℹ️</span>
            <div className="text-sm text-sentineldr-text-primary">
              <strong>IP addresses are configured automatically.</strong> Both nodes discover each other via UDP broadcast.
              No manual IP configuration is required.
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function NodeDetailsCard({ title, node, health, status, icon }) {
  if (!node && !health) {
    return (
      <div className="glass-card rounded-xl p-6">
        <h3 className="text-lg font-semibold text-sentineldr-text-primary mb-4 flex items-center gap-2">
          <span>{icon}</span>
          {title}
        </h3>
        <div className="text-center text-sentineldr-text-muted py-8">
          <div className="text-2xl mb-2">📡</div>
          <div>Node not discovered</div>
        </div>
      </div>
    );
  }
  
  // Use health data if node data not available (for primary)
  const nodeData = node || health;
  
  return (
    <div className="glass-card rounded-xl p-6">
      <h3 className="text-lg font-semibold text-sentineldr-text-primary mb-4 flex items-center gap-2">
        <span>{icon}</span>
        {title}
      </h3>
      
      <div className="space-y-4">
        {/* Basic Info */}
        <div className="grid grid-cols-2 gap-4">
          <InfoField
            label="Node ID"
            value={nodeData?.node_id || 'Unknown'}
            mono
          />
          
          <InfoField
            label="Role"
            value={nodeData?.role || 'Unknown'}
          />
          
          <InfoField
            label="Status"
            value={nodeData?.status || 'Unknown'}
          />
          
          <InfoField
            label="IP Address"
            value={nodeData?.local_ip || nodeData?.peer_host || 'Unknown'}
            mono
          />
        </div>
        
        {/* Timing Info */}
        {nodeData?.uptime_seconds !== undefined && (
          <InfoField
            label="Uptime"
            value={formatUptime(nodeData.uptime_seconds)}
          />
        )}
        
        {nodeData?.peer_last_seen && (
          <InfoField
            label="Last Heartbeat"
            value={formatRelativeTime(nodeData.peer_last_seen)}
          />
        )}
        
        {/* Sync Info */}
        {nodeData?.sync_version !== undefined && (
          <div className="grid grid-cols-2 gap-4">
            <InfoField
              label="Sync Version"
              value={`v${nodeData.sync_version}`}
              mono
            />
            
            {status?.missed_heartbeats !== undefined && (
              <InfoField
                label="Missed Heartbeats"
                value={status.missed_heartbeats.toString()}
              />
            )}
          </div>
        )}
        
        {/* Runtime State */}
        {status && (
          <div className="pt-4 border-t border-sentineldr-purple-primary/20">
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-3">
              Runtime State
            </div>
            
            <div className="space-y-2">
              {status.failover_active !== undefined && (
                <div className="flex justify-between">
                  <span className="text-sm text-sentineldr-text-secondary">Failover Active:</span>
                  <span className={`text-sm font-medium ${
                    status.failover_active ? 'text-sentineldr-warning' : 'text-sentineldr-success'
                  }`}>
                    {status.failover_active ? 'Yes' : 'No'}
                  </span>
                </div>
              )}
              
              {status.peer_status && (
                <div className="flex justify-between">
                  <span className="text-sm text-sentineldr-text-secondary">Peer Status:</span>
                  <span className="text-sm text-sentineldr-text-primary">{status.peer_status}</span>
                </div>
              )}
              
              {status.last_sync_time && (
                <div className="flex justify-between">
                  <span className="text-sm text-sentineldr-text-secondary">Last Sync:</span>
                  <span className="text-sm text-sentineldr-text-primary">
                    {formatRelativeTime(status.last_sync_time)}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function InfoField({ label, value, mono = false }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
        {label}
      </div>
      <div className={`text-sm text-sentineldr-text-primary ${mono ? 'font-mono' : ''}`}>
        {value}
      </div>
    </div>
  );
}