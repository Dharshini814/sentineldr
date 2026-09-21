import React from 'react';
import { NavLink } from 'react-router-dom';
import { useHealth } from '../../hooks/useHealth.js';
import { useEvents } from '../../hooks/useEvents.js';

export function Sidebar() {
  const { health, isHealthy, isFailoverActive } = useHealth();
  const { unacknowledged } = useEvents(10);
  
  const navItems = [
    { path: '/', label: 'Dashboard', icon: '🏠' },
    { path: '/monitoring', label: 'Monitoring', icon: '📊' },
    { path: '/nodes', label: 'Nodes', icon: '🖥️' },
    { path: '/heartbeat', label: 'Heartbeat', icon: '❤️' },
    { path: '/failover', label: 'Failover', icon: '🔄' },
    { path: '/replication', label: 'Replication', icon: '💾' },
    { path: '/network', label: 'Network', icon: '🌐' },
    { 
      path: '/events', 
      label: 'Alerts', 
      icon: '🚨',
      badge: unacknowledged.length > 0 ? unacknowledged.length : null
    },
    { path: '/audit', label: 'Audit Logs', icon: '📜' },
    { path: '/security', label: 'Security', icon: '🔐' },
    { path: '/settings', label: 'Settings', icon: '⚙️' },
  ];
  
  const getSystemStatusText = () => {
    if (isFailoverActive) return 'FAILOVER ACTIVE';
    if (isHealthy) return 'PRIMARY OK';
    return 'DEGRADED';
  };
  
  const getSystemStatusColor = () => {
    if (isFailoverActive) return 'text-sentineldr-warning';
    if (isHealthy) return 'text-sentineldr-success';
    return 'text-sentineldr-critical';
  };
  
  const getSecondaryStatus = () => {
    const peerReachable = health?.peer_reachable;
    if (peerReachable) return 'SECONDARY OK';
    return 'SECONDARY OFFLINE';
  };
  
  const getSecondaryStatusColor = () => {
    const peerReachable = health?.peer_reachable;
    return peerReachable ? 'text-sentineldr-success' : 'text-sentineldr-critical';
  };
  
  return (
    <div className="w-64 h-full glass-card border-r border-sentineldr-purple-primary/20 flex flex-col">
      {/* Header */}
      <div className="p-6 border-b border-sentineldr-purple-primary/20">
        <div className="flex items-center gap-3 mb-2">
          <span className="text-2xl">⬡</span>
          <div>
            <h1 className="font-bold text-lg gradient-text">
              SentinelDR
            </h1>
            <p className="text-xs text-sentineldr-text-muted uppercase tracking-widest">
              DR Platform
            </p>
          </div>
        </div>
      </div>
      
      {/* Navigation */}
      <nav className="flex-1 p-4">
        <ul className="space-y-2">
          {navItems.map((item) => (
            <li key={item.path}>
              <NavLink
                to={item.path}
                className={({ isActive }) => `
                  flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200
                  ${isActive 
                    ? 'bg-sentineldr-purple-primary/20 text-sentineldr-purple-light border-l-4 border-sentineldr-purple-primary' 
                    : 'text-sentineldr-text-secondary hover:text-sentineldr-text-primary hover:bg-sentineldr-bg-raised/50'
                  }
                `}
              >
                <span className="text-lg">{item.icon}</span>
                <span className="font-medium">{item.label}</span>
                {item.badge && (
                  <span className="ml-auto bg-sentineldr-critical text-white text-xs font-bold px-2 py-1 rounded-full min-w-[20px] text-center">
                    {item.badge > 99 ? '99+' : item.badge}
                  </span>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      
      {/* System Status */}
      <div className="p-4 border-t border-sentineldr-purple-primary/20">
        <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-3">
          System Status
        </div>
        
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className={`status-dot ${isHealthy ? 'online' : 'offline'}`} />
            <span className={`text-sm font-medium ${getSystemStatusColor()}`}>
              {getSystemStatusText()}
            </span>
          </div>
          
          <div className="flex items-center gap-2">
            <span className={`status-dot ${health?.peer_reachable ? 'online' : 'offline'}`} />
            <span className={`text-sm font-medium ${getSecondaryStatusColor()}`}>
              {getSecondaryStatus()}
            </span>
          </div>
        </div>
        
        {isFailoverActive && (
          <div className="mt-3 p-2 bg-sentineldr-warning/20 border border-sentineldr-warning/30 rounded text-xs text-sentineldr-warning">
            ⚠️ DR Mode Active
          </div>
        )}
      </div>
    </div>
  );
}