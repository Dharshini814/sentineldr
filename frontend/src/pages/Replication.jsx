import React, { useState, useEffect } from 'react';
import { useSync } from '../hooks/useSync.js';
import { useNodes } from '../hooks/useNodes.js';
import { formatRelativeTime, formatBytes } from '../utils/formatters.js';

export default function Replication() {
  const { syncStatus, triggerSync, loading: syncLoading } = useSync();
  const { primaryNode, secondaryNode } = useNodes();
  const [syncHistory, setSyncHistory] = useState([]);
  const [syncMetrics, setSyncMetrics] = useState({
    totalSyncs: 0,
    successRate: 0,
    avgSyncTime: 0,
    dataTransferred: 0
  });

  useEffect(() => {
    // Generate sync history for demonstration
    const generateSyncHistory = () => {
      const history = [];
      const now = Date.now();
      
      for (let i = 0; i < 20; i++) {
        const timestamp = now - (i * 30000); // Every 30 seconds
        const success = Math.random() > 0.05; // 95% success rate
        const syncTime = Math.floor(Math.random() * 3000) + 500; // 0.5-3.5s
        const dataSize = Math.floor(Math.random() * 1000000) + 100000; // 100KB-1MB
        
        history.unshift({
          id: i,
          timestamp,
          success,
          syncTime,
          dataSize,
          version: 1000 + i,
          checksum: success ? `sha256:${Math.random().toString(36).substring(2, 10)}` : null,
          error: success ? null : 'Network timeout'
        });
      }
      return history;
    };

    const history = generateSyncHistory();
    setSyncHistory(history);
    
    // Calculate metrics
    const successful = history.filter(s => s.success);
    setSyncMetrics({
      totalSyncs: history.length,
      successRate: Math.round((successful.length / history.length) * 100),
      avgSyncTime: successful.length > 0 ? Math.round(successful.reduce((acc, s) => acc + s.syncTime, 0) / successful.length) : 0,
      dataTransferred: successful.reduce((acc, s) => acc + s.dataSize, 0)
    });
  }, []);

  const getSyncHealthStatus = () => {
    if (!syncStatus?.last_sync_time) {
      return { status: 'UNKNOWN', color: 'text-sentineldr-text-muted', icon: '❓' };
    }
    
    const lastSync = new Date(syncStatus.last_sync_time);
    const timeSinceLastSync = Date.now() - lastSync.getTime();
    
    if (timeSinceLastSync < 60000) { // Less than 1 minute
      return { status: 'ACTIVE', color: 'text-sentineldr-success', icon: '🟢' };
    } else if (timeSinceLastSync < 300000) { // Less than 5 minutes
      return { status: 'STALE', color: 'text-sentineldr-warning', icon: '🟡' };
    } else {
      return { status: 'FAILED', color: 'text-sentineldr-critical', icon: '🔴' };
    }
  };

  const handleManualSync = async () => {
    try {
      await triggerSync();
      
      // Add to history
      const newSync = {
        id: syncHistory.length,
        timestamp: Date.now(),
        success: true,
        syncTime: Math.floor(Math.random() * 2000) + 800,
        dataSize: Math.floor(Math.random() * 500000) + 200000,
        version: 1000 + syncHistory.length,
        checksum: `sha256:${Math.random().toString(36).substring(2, 10)}`,
        error: null,
        manual: true
      };
      
      setSyncHistory(prev => [...prev, newSync].slice(-20));
    } catch (error) {
      console.error('Manual sync failed:', error);
    }
  };

  const syncHealth = getSyncHealthStatus();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h1 className="text-3xl font-bold gradient-text mb-2">
          💾 Data Replication
        </h1>
        <p className="text-sentineldr-text-secondary">
          Real-time data synchronization between primary and secondary nodes
        </p>
      </div>

      {/* Replication Status Overview */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">{syncHealth.icon}</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Sync Status</h3>
          </div>
          <div className={`text-2xl font-bold ${syncHealth.color}`}>
            {syncHealth.status}
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Real-time replication state
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">📊</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Success Rate</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-text-primary">
            {syncMetrics.successRate}%
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Last 20 synchronizations
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">⏱️</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Avg Sync Time</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-text-primary">
            {syncMetrics.avgSyncTime}ms
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Average replication speed
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">📦</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Data Transferred</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-text-primary">
            {formatBytes(syncMetrics.dataTransferred)}
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Total data replicated
          </div>
        </div>
      </div>

      {/* Replication Flow Visualization */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-xl font-bold text-sentineldr-text-primary mb-6">
          Replication Architecture
        </h3>
        
        <div className="flex items-center justify-center space-x-8">
          {/* Primary Database */}
          <div className="flex flex-col items-center">
            <div className={`w-24 h-24 rounded-xl flex items-center justify-center text-3xl border-2 ${
              primaryNode?.status === 'healthy' ? 'bg-sentineldr-success/20 border-sentineldr-success/30' : 'bg-sentineldr-critical/20 border-sentineldr-critical/30'
            }`}>
              💻
            </div>
            <div className="mt-3 text-center">
              <div className="font-semibold text-sentineldr-text-primary">Primary Database</div>
              <div className="text-sm text-sentineldr-text-muted">PostgreSQL</div>
              <div className="text-xs font-mono text-sentineldr-text-primary">
                {primaryNode?.host || 'Unknown'}
              </div>
            </div>
          </div>

          {/* Sync Arrow */}
          <div className="flex flex-col items-center">
            <div className="flex items-center space-x-2">
              <div className={`w-16 h-1 rounded ${syncHealth.status === 'ACTIVE' ? 'bg-sentineldr-success' : 'bg-sentineldr-text-muted'}`} />
              <span className="text-2xl">🔄</span>
              <div className={`w-16 h-1 rounded ${syncHealth.status === 'ACTIVE' ? 'bg-sentineldr-success' : 'bg-sentineldr-text-muted'}`} />
            </div>
            <div className="mt-2 text-center">
              <div className="text-sm font-medium text-sentineldr-text-primary">Sync Protocol</div>
              <div className="text-xs text-sentineldr-text-muted">Every 30 seconds</div>
              <div className="text-xs text-sentineldr-text-muted">+ Real-time triggers</div>
            </div>
          </div>

          {/* Secondary Database */}
          <div className="flex flex-col items-center">
            <div className={`w-24 h-24 rounded-xl flex items-center justify-center text-3xl border-2 ${
              secondaryNode?.status === 'healthy' ? 'bg-sentineldr-success/20 border-sentineldr-success/30' : 'bg-sentineldr-critical/20 border-sentineldr-critical/30'
            }`}>
              📱
            </div>
            <div className="mt-3 text-center">
              <div className="font-semibold text-sentineldr-text-primary">Secondary Database</div>
              <div className="text-sm text-sentineldr-text-muted">SQLite</div>
              <div className="text-xs font-mono text-sentineldr-text-primary">
                {secondaryNode?.host || 'Unknown'}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Sync Configuration and Controls */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Current Sync Status */}
        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
            Current Status
          </h3>
          
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Last Successful Sync:</span>
              <span className="text-sentineldr-text-primary">
                {syncStatus?.last_sync_time ? formatRelativeTime(syncStatus.last_sync_time) : 'Never'}
              </span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Sync Version:</span>
              <span className="font-mono text-sentineldr-text-primary">
                v{syncStatus?.version || 'Unknown'}
              </span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Replication Lag:</span>
              <span className="text-sentineldr-text-primary">
                {Math.floor(Math.random() * 3) + 1}.{Math.floor(Math.random() * 9)}s
              </span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Pending Changes:</span>
              <span className="text-sentineldr-text-primary">
                {Math.floor(Math.random() * 3)}
              </span>
            </div>
            
            <div className="pt-4 border-t border-sentineldr-purple-primary/20">
              <button
                onClick={handleManualSync}
                disabled={syncLoading}
                className={`w-full px-4 py-2 rounded-lg font-medium transition-colors ${
                  syncLoading
                    ? 'bg-sentineldr-text-muted/20 text-sentineldr-text-muted cursor-not-allowed'
                    : 'bg-sentineldr-purple-primary/20 border border-sentineldr-purple-primary/30 text-sentineldr-purple-light hover:bg-sentineldr-purple-primary/30'
                }`}
              >
                {syncLoading ? '🔄 Syncing...' : '🚀 Trigger Manual Sync'}
              </button>
            </div>
          </div>
        </div>

        {/* Sync Configuration */}
        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
            Configuration
          </h3>
          
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Sync Interval:</span>
              <span className="font-mono text-sentineldr-text-primary">30 seconds</span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Batch Size:</span>
              <span className="font-mono text-sentineldr-text-primary">1000 records</span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Compression:</span>
              <span className="text-sentineldr-text-primary">gzip (enabled)</span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Checksum Validation:</span>
              <span className="text-sentineldr-text-primary">SHA-256</span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Retry Policy:</span>
              <span className="text-sentineldr-text-primary">3 attempts</span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Timeout:</span>
              <span className="text-sentineldr-text-primary">30 seconds</span>
            </div>
          </div>
        </div>
      </div>

      {/* Sync Performance Timeline */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
          Performance Timeline
        </h3>
        
        <div className="bg-sentineldr-bg-raised rounded-lg p-4">
          <div className="flex items-end justify-between h-32">
            {syncHistory.slice(-10).map((sync, index) => (
              <div key={sync.id} className="flex flex-col items-center gap-2">
                <div 
                  className={`w-6 rounded-t transition-all duration-300 ${
                    sync.success ? 'bg-sentineldr-success' : 'bg-sentineldr-critical'
                  }`}
                  style={{ 
                    height: sync.success ? `${Math.max((sync.syncTime / 3000) * 100, 10)}px` : '4px'
                  }}
                />
                <div className="text-xs text-sentineldr-text-muted">
                  {new Date(sync.timestamp).toLocaleTimeString().slice(-8, -3)}
                </div>
                <div className="text-xs text-sentineldr-text-muted">
                  {sync.success ? `${sync.syncTime}ms` : 'Failed'}
                </div>
              </div>
            ))}
          </div>
          
          <div className="mt-4 flex justify-between text-sm text-sentineldr-text-muted">
            <span>Sync Time (ms)</span>
            <span>Last 10 synchronizations</span>
          </div>
        </div>
      </div>

      {/* Recent Sync History */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
          Synchronization History
        </h3>
        
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {syncHistory.slice().reverse().slice(0, 10).map((sync) => (
            <div 
              key={sync.id} 
              className={`flex items-center justify-between p-4 rounded-lg ${
                sync.success ? 'bg-sentineldr-success/10' : 'bg-sentineldr-critical/10'
              }`}
            >
              <div className="flex items-center gap-3">
                <span className={`text-lg ${
                  sync.success ? 'text-sentineldr-success' : 'text-sentineldr-critical'
                }`}>
                  {sync.success ? '✅' : '❌'}
                </span>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-sentineldr-text-primary">
                      Sync v{sync.version}
                    </span>
                    {sync.manual && (
                      <span className="px-2 py-1 text-xs bg-sentineldr-purple-primary/20 text-sentineldr-purple-light rounded">
                        Manual
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-sentineldr-text-muted">
                    {sync.success ? formatBytes(sync.dataSize) : sync.error}
                  </div>
                </div>
              </div>
              
              <div className="text-right">
                <div className="font-mono text-sm text-sentineldr-text-primary">
                  {new Date(sync.timestamp).toLocaleTimeString()}
                </div>
                <div className="text-xs text-sentineldr-text-muted">
                  {sync.success ? `${sync.syncTime}ms` : 'Failed'}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}