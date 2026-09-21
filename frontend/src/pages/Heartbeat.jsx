import React, { useState, useEffect } from 'react';
import { useHealth } from '../hooks/useHealth.js';
import { useNodes } from '../hooks/useNodes.js';
import { formatRelativeTime } from '../utils/formatters.js';

export default function Heartbeat() {
  const { health, phoneHealth } = useHealth();
  const { primaryNode, secondaryNode } = useNodes();
  const [heartbeatHistory, setHeartbeatHistory] = useState([]);
  const [missedHeartbeats, setMissedHeartbeats] = useState(0);

  useEffect(() => {
    // Simulate heartbeat history for demo
    const generateHeartbeatHistory = () => {
      const history = [];
      const now = Date.now();
      
      for (let i = 0; i < 20; i++) {
        const timestamp = now - (i * 3000); // Every 3 seconds
        const responseTime = Math.floor(Math.random() * 40) + 15; // 15-55ms
        const success = Math.random() > 0.05; // 95% success rate
        
        history.unshift({
          timestamp,
          responseTime: success ? responseTime : null,
          success,
          id: i
        });
      }
      return history;
    };

    setHeartbeatHistory(generateHeartbeatHistory());
    
    // Update history every 3 seconds
    const interval = setInterval(() => {
      setHeartbeatHistory(prev => {
        const newEntry = {
          timestamp: Date.now(),
          responseTime: Math.floor(Math.random() * 40) + 15,
          success: Math.random() > 0.05,
          id: prev.length
        };
        
        const updated = [...prev, newEntry].slice(-20); // Keep last 20
        
        // Count missed heartbeats
        const missed = updated.filter(h => !h.success).length;
        setMissedHeartbeats(missed);
        
        return updated;
      });
    }, 3000);

    return () => clearInterval(interval);
  }, []);

  const getHeartbeatStatus = () => {
    const healthData = health || phoneHealth;
    if (!healthData) return { status: 'unknown', color: 'text-sentineldr-text-muted' };
    
    const recentFailed = heartbeatHistory.slice(-5).filter(h => !h.success).length;
    
    if (recentFailed === 0) {
      return { status: 'HEALTHY', color: 'text-sentineldr-success' };
    } else if (recentFailed < 3) {
      return { status: 'WARNING', color: 'text-sentineldr-warning' };
    } else {
      return { status: 'CRITICAL', color: 'text-sentineldr-critical' };
    }
  };

  const getAverageResponseTime = () => {
    const successful = heartbeatHistory.filter(h => h.success && h.responseTime);
    if (successful.length === 0) return 0;
    
    const sum = successful.reduce((acc, h) => acc + h.responseTime, 0);
    return Math.round(sum / successful.length);
  };

  const getNextExpectedHeartbeat = () => {
    const lastHeartbeat = heartbeatHistory[heartbeatHistory.length - 1];
    if (!lastHeartbeat) return 'Unknown';
    
    const nextTime = new Date(lastHeartbeat.timestamp + 3000);
    return nextTime.toLocaleTimeString();
  };

  const heartbeatStatus = getHeartbeatStatus();
  const avgResponseTime = getAverageResponseTime();

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h1 className="text-3xl font-bold gradient-text mb-2">
          ❤️ Heartbeat Monitoring
        </h1>
        <p className="text-sentineldr-text-secondary">
          Real-time inter-node connectivity and health monitoring
        </p>
      </div>

      {/* Heartbeat Status Overview */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">💓</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Heartbeat Status</h3>
          </div>
          <div className={`text-2xl font-bold ${heartbeatStatus.color}`}>
            {heartbeatStatus.status}
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Overall connectivity health
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">⏱️</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Interval</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-text-primary">
            3 seconds
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Heartbeat frequency
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">📊</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Response Time</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-text-primary">
            {avgResponseTime}ms
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Average latency
          </div>
        </div>

        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-3 mb-4">
            <span className="text-2xl">❌</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Missed</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-text-primary">
            {missedHeartbeats}
          </div>
          <div className="text-sm text-sentineldr-text-muted mt-1">
            Failed heartbeats
          </div>
        </div>
      </div>

      {/* Connection Details */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Primary → Secondary */}
        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xl font-bold text-sentineldr-text-primary">
              Primary → Secondary
            </h3>
            <span className={`px-3 py-1 rounded-full text-sm font-medium ${
              primaryNode?.status === 'healthy' ? 'bg-sentineldr-success/20 text-sentineldr-success' : 'bg-sentineldr-critical/20 text-sentineldr-critical'
            }`}>
              {primaryNode?.status === 'healthy' ? 'ACTIVE' : 'OFFLINE'}
            </span>
          </div>
          
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Source:</span>
              <span className="font-mono text-sentineldr-text-primary">
                {primaryNode?.host || 'Unknown'} : {primaryNode?.port || '8000'}
              </span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Target:</span>
              <span className="font-mono text-sentineldr-text-primary">
                {secondaryNode?.host || 'Unknown'} : {secondaryNode?.port || '8001'}
              </span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Last Heartbeat:</span>
              <span className="text-sentineldr-text-primary">
                {health?.timestamp ? formatRelativeTime(health.timestamp) : 'Unknown'}
              </span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Next Expected:</span>
              <span className="text-sentineldr-text-primary">
                {getNextExpectedHeartbeat()}
              </span>
            </div>
          </div>
        </div>

        {/* Heartbeat Configuration */}
        <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
          <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
            Configuration
          </h3>
          
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Heartbeat Interval:</span>
              <span className="text-sentineldr-text-primary font-mono">3 seconds</span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Timeout Threshold:</span>
              <span className="text-sentineldr-text-primary font-mono">10 seconds</span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Failure Threshold:</span>
              <span className="text-sentineldr-text-primary font-mono">3 missed</span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Retry Attempts:</span>
              <span className="text-sentineldr-text-primary font-mono">3 attempts</span>
            </div>
            
            <div className="flex justify-between items-center">
              <span className="text-sentineldr-text-muted">Protocol:</span>
              <span className="text-sentineldr-text-primary font-mono">HTTP/REST</span>
            </div>
          </div>
        </div>
      </div>

      {/* Response Time Graph */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
          Response Time Timeline
        </h3>
        
        <div className="bg-sentineldr-bg-raised rounded-lg p-4">
          <div className="flex items-end justify-between h-32">
            {heartbeatHistory.slice(-10).map((heartbeat, index) => (
              <div key={heartbeat.id} className="flex flex-col items-center gap-2">
                <div 
                  className={`w-4 rounded-t transition-all duration-300 ${
                    heartbeat.success ? 'bg-sentineldr-success' : 'bg-sentineldr-critical'
                  }`}
                  style={{ 
                    height: heartbeat.success ? `${(heartbeat.responseTime / 60) * 100}px` : '4px'
                  }}
                />
                <div className="text-xs text-sentineldr-text-muted">
                  {new Date(heartbeat.timestamp).toLocaleTimeString().slice(-8, -3)}
                </div>
                <div className="text-xs text-sentineldr-text-muted">
                  {heartbeat.success ? `${heartbeat.responseTime}ms` : 'X'}
                </div>
              </div>
            ))}
          </div>
          
          <div className="mt-4 flex justify-between text-sm text-sentineldr-text-muted">
            <span>Response Time (ms)</span>
            <span>Last 10 heartbeats</span>
          </div>
        </div>
      </div>

      {/* Recent Heartbeat Log */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-xl font-bold text-sentineldr-text-primary mb-4">
          Recent Heartbeat Log
        </h3>
        
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {heartbeatHistory.slice().reverse().slice(0, 10).map((heartbeat) => (
            <div 
              key={heartbeat.id} 
              className={`flex items-center justify-between p-3 rounded-lg ${
                heartbeat.success ? 'bg-sentineldr-success/10' : 'bg-sentineldr-critical/10'
              }`}
            >
              <div className="flex items-center gap-3">
                <span className={`text-lg ${
                  heartbeat.success ? 'text-sentineldr-success' : 'text-sentineldr-critical'
                }`}>
                  {heartbeat.success ? '✅' : '❌'}
                </span>
                <div>
                  <div className="font-mono text-sm text-sentineldr-text-primary">
                    {new Date(heartbeat.timestamp).toLocaleTimeString()}
                  </div>
                  <div className="text-xs text-sentineldr-text-muted">
                    {heartbeat.success ? 'Heartbeat received' : 'Heartbeat failed'}
                  </div>
                </div>
              </div>
              
              <div className="text-right">
                <div className="font-mono text-sm text-sentineldr-text-primary">
                  {heartbeat.success ? `${heartbeat.responseTime}ms` : 'Timeout'}
                </div>
                <div className="text-xs text-sentineldr-text-muted">
                  {formatRelativeTime(heartbeat.timestamp)}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}