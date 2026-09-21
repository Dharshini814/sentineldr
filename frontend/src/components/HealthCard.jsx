import React from 'react';

export function HealthCard({ title, status, value, subtitle, icon }) {
  const getStatusColor = (status) => {
    switch (status?.toLowerCase()) {
      case 'healthy':
      case 'ok':
      case 'active':
        return 'text-sentineldr-success';
      case 'warning':
      case 'degraded':
        return 'text-sentineldr-warning';
      case 'critical':
      case 'error':
      case 'offline':
        return 'text-sentineldr-critical';
      case 'info':
        return 'text-sentineldr-info';
      default:
        return 'text-sentineldr-text-muted';
    }
  };
  
  const getStatusIcon = (status) => {
    switch (status?.toLowerCase()) {
      case 'healthy':
      case 'ok':
      case 'active':
        return '✅';
      case 'warning':
      case 'degraded':
        return '⚠️';
      case 'critical':
      case 'error':
      case 'offline':
        return '🚨';
      case 'info':
        return 'ℹ️';
      default:
        return '⭕';
    }
  };
  
  const statusColor = getStatusColor(status);
  const statusIcon = icon || getStatusIcon(status);
  
  return (
    <div className="glass-card rounded-xl p-4">
      <div className="flex items-start gap-3">
        <span className="text-2xl">{statusIcon}</span>
        
        <div className="flex-1 min-w-0">
          <div className="text-xs uppercase tracking-widest text-sentineldr-text-muted mb-1">
            {title}
          </div>
          
          <div className={`font-semibold ${statusColor}`}>
            {status}
          </div>
          
          {value && (
            <div className="text-sm text-sentineldr-text-primary mt-1">
              {value}
            </div>
          )}
          
          {subtitle && (
            <div className="text-xs text-sentineldr-text-secondary mt-1">
              {subtitle}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}