import React from 'react';
import { formatRelativeTime, formatChecksum } from '../utils/formatters.js';
import { NeumorphicButton } from './NeumorphicButton.jsx';

export function SyncStatus({ syncStatus, onTriggerSync, loading }) {
  if (!syncStatus && !loading) {
    return (
      <div className="glass-card rounded-xl p-6">
        <div className="text-center text-sentineldr-text-muted">
          <span className="text-2xl">🔄</span>
          <div className="mt-2">Sync status unavailable</div>
        </div>
      </div>
    );
  }
  
  if (loading && !syncStatus) {
    return (
      <div className="glass-card rounded-xl p-6">
        <div className="flex items-center justify-center gap-3">
          <div className="w-5 h-5 border-2 border-sentineldr-purple-primary border-t-transparent rounded-full animate-spin" />
          <span className="text-sentineldr-text-secondary">Loading sync status...</span>
        </div>
      </div>
    );
  }
  
  const lastSync = syncStatus?.last_sync_time;
  const version = syncStatus?.sync_version || 0;
  const checksum = syncStatus?.last_sync_checksum;
  const interval = syncStatus?.sync_interval || 5;
  
  // Check if sync is recent (within last 5 seconds)
  const isRecentSync = lastSync && (Date.now() - new Date(lastSync).getTime()) < 5000;
  
  return (
    <div className="glass-card rounded-xl p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className={`text-2xl ${isRecentSync ? 'animate-pulse' : ''}`}>
            🔄
          </span>
          <h3 className="text-lg font-semibold text-sentineldr-text-primary">
            Synchronization Status
          </h3>
        </div>
        
        <NeumorphicButton
          label="Sync Now"
          onClick={onTriggerSync}
          loading={loading}
          size="sm"
          variant="primary"
        />
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div>
          <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
            Version
          </div>
          <div className="font-mono text-lg font-semibold text-sentineldr-purple-light">
            v{version}
          </div>
        </div>
        
        <div>
          <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
            Last Sync
          </div>
          <div className="text-sm text-sentineldr-text-primary">
            {lastSync ? formatRelativeTime(lastSync) : 'Never'}
          </div>
        </div>
        
        <div>
          <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
            Checksum
          </div>
          <div className="font-mono text-sm text-sentineldr-text-primary">
            {checksum ? formatChecksum(checksum) : 'none'}
          </div>
        </div>
        
        <div>
          <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
            Interval
          </div>
          <div className="text-sm text-sentineldr-text-primary">
            Every {interval}s
          </div>
        </div>
      </div>
      
      {/* Sync Animation Indicator */}
      {isRecentSync && (
        <div className="mt-4 pt-4 border-t border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-2 text-sentineldr-success">
            <div className="flex items-center gap-1">
              <span className="animate-pulse">📡</span>
              <span className="text-sm">→</span>
              <span className="animate-pulse">📱</span>
            </div>
            <span className="text-sm font-medium">
              Sync Active
            </span>
          </div>
        </div>
      )}
    </div>
  );
}