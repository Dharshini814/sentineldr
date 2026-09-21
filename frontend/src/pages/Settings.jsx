import React from 'react';
import { useHealth } from '../hooks/useHealth.js';
import { useSync } from '../hooks/useSync.js';

export default function Settings() {
  const { health, status } = useHealth();
  const { syncStatus } = useSync();

  const configItems = [
    {
      category: 'API Configuration',
      items: [
        {
          label: 'API URL',
          value: import.meta.env.VITE_API_URL || 'http://localhost:8000',
          description: 'Base URL for API requests'
        },
        {
          label: 'API Key Status',
          value: import.meta.env.VITE_API_KEY ? 'Configured ✓' : '⚠ Not Set',
          description: 'Authentication key for API access'
        }
      ]
    },
    {
      category: 'Node Configuration',
      items: [
        {
          label: 'Primary Node ID',
          value: health?.node_id || 'Not connected',
          description: 'Live identifier from primary node'
        },
        {
          label: 'Primary Node IP',
          value: health?.local_ip || 'Unknown',
          description: 'Live IP address from primary node'
        },
        {
          label: 'Secondary Node ID',
          value: health?.peer_node_id || 'Not discovered',
          description: 'Live identifier from secondary node'
        },
        {
          label: 'Secondary Node IP',
          value: health?.peer_host || 'Not discovered',
          description: 'Live IP address from secondary node'
        }
      ]
    },
    {
      category: 'Timing Configuration',
      items: [
        {
          label: 'Heartbeat Interval',
          value: status?.heartbeat_interval ? `${status.heartbeat_interval}s` : '3s',
          description: 'How often heartbeats are sent between nodes'
        },
        {
          label: 'Sync Interval',
          value: syncStatus?.sync_interval ? `${syncStatus.sync_interval}s` : '3s',
          description: 'How often data synchronization occurs'
        },
        {
          label: 'Failover Threshold',
          value: status?.missed_heartbeat_threshold
            ? `${status.missed_heartbeat_threshold} missed heartbeat(s) (${status.missed_heartbeat_threshold * 3}s)`
            : '1 missed heartbeat (3s)',
          description: 'Trigger point for automatic failover'
        }
      ]
    },
    {
      category: 'Network Discovery',
      items: [
        {
          label: 'Discovery Protocol',
          value: 'UDP Broadcast',
          description: 'Method for automatic peer detection'
        },
        {
          label: 'Discovery Port',
          value: '47777',
          description: 'Port used for node discovery'
        },
        {
          label: 'Primary Port',
          value: '8000',
          description: 'HTTP port for primary node'
        },
        {
          label: 'Secondary Port',
          value: '8001',
          description: 'HTTP port for secondary node'
        }
      ]
    }
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-sentineldr-text-primary mb-2">Settings</h1>
        <p className="text-sentineldr-text-secondary">Live system configuration and status</p>
      </div>

      <div className="glass-card border-sentineldr-info/50 bg-sentineldr-info/10 rounded-xl p-6">
        <div className="flex items-start gap-3">
          <span className="text-2xl">ℹ️</span>
          <div>
            <h3 className="font-semibold text-sentineldr-info mb-2">Automatic Network Configuration</h3>
            <p className="text-sentineldr-text-primary">
              IP addresses are configured automatically via UDP broadcast. All values shown are live from the running nodes.
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-6">
        {configItems.map((section) => (
          <div key={section.category} className="glass-card rounded-xl p-6">
            <h3 className="text-lg font-semibold text-sentineldr-text-primary mb-4">{section.category}</h3>
            <div className="space-y-4">
              {section.items.map((item) => (
                <ConfigItem key={item.label} label={item.label} value={item.value} description={item.description} />
              ))}
            </div>
          </div>
        ))}
      </div>

      {(health || status) && (
        <div className="glass-card rounded-xl p-6">
          <h3 className="text-lg font-semibold text-sentineldr-text-primary mb-4">Live Runtime State</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {health && (
              <div>
                <h4 className="font-medium text-sentineldr-text-primary mb-3">Health</h4>
                <div className="space-y-2">
                  <StatusItem label="Node Status" value={health.status} />
                  <StatusItem label="Peer Reachable" value={health.peer_reachable ? 'Yes ✓' : 'No ✗'} />
                  <StatusItem label="Failover Active" value={health.failover_active ? '⚠ Yes' : 'No'} />
                  <StatusItem label="Sync Version" value={`v${health.sync_version ?? 0}`} mono />
                </div>
              </div>
            )}
            {status && (
              <div>
                <h4 className="font-medium text-sentineldr-text-primary mb-3">Runtime</h4>
                <div className="space-y-2">
                  <StatusItem label="Peer Status" value={status.peer_status || 'unknown'} />
                  <StatusItem label="Missed Heartbeats" value={String(status.missed_heartbeats ?? 0)} />
                  <StatusItem label="Heartbeat Sequence" value={String(status.heartbeat_sequence ?? 0)} mono />
                  <StatusItem label="DB Connection" value={status.database || 'unknown'} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="glass-card border-sentineldr-warning/50 bg-sentineldr-warning/10 rounded-xl p-6">
        <div className="flex items-start gap-3">
          <span className="text-2xl">⚠️</span>
          <div>
            <h3 className="font-semibold text-sentineldr-warning mb-2">Read-Only View</h3>
            <p className="text-sentineldr-text-primary">
              Configuration changes must be made in the environment files (.env.laptop, .env.phone) and require a server restart.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function ConfigItem({ label, value, description }) {
  return (
    <div className="flex items-start justify-between py-3 border-b border-sentineldr-purple-primary/10 last:border-b-0">
      <div className="flex-1">
        <div className="font-medium text-sentineldr-text-primary mb-1">{label}</div>
        <div className="text-sm text-sentineldr-text-secondary">{description}</div>
      </div>
      <div className="ml-4 text-right">
        <div className="font-mono text-sm text-sentineldr-purple-light bg-sentineldr-bg-raised px-3 py-1 rounded">
          {value}
        </div>
      </div>
    </div>
  );
}

function StatusItem({ label, value, mono = false }) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-sm text-sentineldr-text-secondary">{label}:</span>
      <span className={`text-sm text-sentineldr-text-primary ${mono ? 'font-mono' : ''}`}>{value}</span>
    </div>
  );
}