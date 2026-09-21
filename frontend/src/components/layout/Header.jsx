import React from 'react';
import { getSystemStatus } from '../../utils/severity.js';
import { NeumorphicButton } from '../NeumorphicButton.jsx';

export function Header({ 
  title, 
  health, 
  nodes, 
  onRefresh, 
  loading = false 
}) {
  const systemStatus = getSystemStatus(health, nodes);
  
  return (
    <header className="glass-card border-b border-sentineldr-purple-primary/20 px-6 py-4">
      <div className="flex items-center justify-between">
        {/* Page Title */}
        <div>
          <h1 className="text-2xl font-semibold text-sentineldr-text-primary">
            {title}
          </h1>
        </div>
        
        {/* Right Side Actions */}
        <div className="flex items-center gap-4">
          {/* System Status Badge */}
          <div className="flex items-center gap-2 px-3 py-2 bg-sentineldr-bg-raised/50 border border-sentineldr-purple-primary/20 rounded-lg">
            <span className={`status-dot ${health?.status === 'healthy' ? 'online' : 'offline'}`} />
            <span className={`font-medium text-sm ${systemStatus.color}`}>
              {systemStatus.status}
            </span>
          </div>
          
          {/* Refresh Button */}
          <NeumorphicButton
            icon="🔄"
            onClick={onRefresh}
            loading={loading}
            variant="ghost"
            size="md"
            className="min-w-[48px]"
          />
        </div>
      </div>
    </header>
  );
}