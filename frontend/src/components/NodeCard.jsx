import React from 'react';
import { formatUptime, formatRelativeTime, formatIP } from '../utils/formatters.js';
import { getNodeRoleColor } from '../utils/severity.js';

export function NodeCard({ node, type }) {
  if (!node) {
    return (
      <div className="glass-card rounded-xl p-6">
        <div className="text-center text-sentineldr-text-muted">
          <div className="text-4xl mb-2">📱</div>
          <div className="text-lg font-medium">No {type} Node</div>
          <div className="text-sm">Node not discovered</div>
        </div>
      </div>
    );
  }
  
  const isOnline = node.status === 'healthy' || node.status === 'online';
  const isFailover = node.failover_active;
  const role = node.role || type;
  
  let borderClass = 'border-sentineldr-purple-primary/20';
  if (!isOnline) {
    borderClass = 'border-sentineldr-critical animate-breathe';
  } else if (isFailover) {
    borderClass = 'border-sentineldr-warning animate-breathe';
  }
  
  const roleIcon = type === 'primary' ? '💻' : '📱';
  
  // Get the correct IP address from the node data
  // Both primary and secondary should use 'host' field from backend API
  // Backend ensures 'host' contains the correct IP for each node type
  const ipAddress = node.host;
  
  return (
    <div className={`glass-card rounded-xl p-6 border ${borderClass}`}>
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className="text-3xl">{roleIcon}</span>
          <div>
            <h3 className="font-semibold text-sentineldr-text-primary">
              {node.node_id || 'Unknown Node'}
            </h3>
            <div className="flex items-center gap-2 mt-1">
              <span className={`
                px-2 py-1 text-xs font-medium rounded border
                ${getNodeRoleColor(role)}
              `}>
                {role?.toUpperCase().replace('_', ' ')}
              </span>
              {isFailover && (
                <span className="px-2 py-1 text-xs font-medium rounded border border-sentineldr-warning/30 bg-sentineldr-warning/20 text-sentineldr-warning">
                  FAILOVER ACTIVE
                </span>
              )}
            </div>
          </div>
        </div>
        
        {/* Status Indicator */}
        <div className="flex items-center gap-2">
          <span className={`status-dot ${isOnline ? 'online' : 'offline'}`} />
          <span className={`text-sm font-medium ${isOnline ? 'text-sentineldr-success' : 'text-sentineldr-critical'}`}>
            {isOnline ? 'Online' : 'Offline'}
          </span>
        </div>
      </div>
      
      {/* Details */}
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
              IP Address
            </div>
            <div className="font-mono text-sm text-sentineldr-text-primary">
              {formatIP(ipAddress)}
            </div>
          </div>
          
          <div>
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
              Port
            </div>
            <div className="font-mono text-sm text-sentineldr-text-primary">
              {node.port || 'unknown'}
            </div>
          </div>
        </div>
        
        {node.uptime_seconds !== undefined && (
          <div>
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
              Uptime
            </div>
            <div className="text-sm text-sentineldr-text-primary">
              {formatUptime(node.uptime_seconds)}
            </div>
          </div>
        )}
        
        {node.last_seen && (
          <div>
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
              Last Heartbeat
            </div>
            <div className="text-sm text-sentineldr-text-primary">
              {formatRelativeTime(node.last_seen)}
            </div>
          </div>
        )}
        
        {node.sync_version !== undefined && (
          <div>
            <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
              Sync Version
            </div>
            <div className="font-mono text-sm text-sentineldr-text-primary">
              v{node.sync_version}
            </div>
          </div>
        )}
      </div>
      
      {/* Footer Status */}
      {!isOnline && (
        <div className="mt-4 pt-4 border-t border-sentineldr-critical/20">
          <div className="flex items-center gap-2 text-sentineldr-critical">
            <span className="text-lg">⚠️</span>
            <span className="text-sm font-medium">
              Node Unreachable
            </span>
          </div>
        </div>
      )}
    </div>
  );
}