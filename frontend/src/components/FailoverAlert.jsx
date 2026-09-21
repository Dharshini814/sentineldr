import React, { useState } from 'react';
import { formatTimestamp } from '../utils/formatters.js';
import { NeumorphicButton } from './NeumorphicButton.jsx';

export function FailoverAlert({ 
  isActive, 
  failoverTime, 
  onAcknowledge, 
  acknowledged = false 
}) {
  const [isAcknowledging, setIsAcknowledging] = useState(false);
  
  if (!isActive) return null;
  
  const handleAcknowledge = async () => {
    setIsAcknowledging(true);
    try {
      await onAcknowledge?.();
    } catch (error) {
      console.error('Failed to acknowledge failover:', error);
    } finally {
      setIsAcknowledging(false);
    }
  };
  
  return (
    <div className="w-full animate-[slideDown_0.3s_ease-out] mb-6">
      <div className="glass-card border-sentineldr-critical/50 bg-sentineldr-critical/10 animate-breathe rounded-xl p-6">
        <div className="flex items-start gap-4">
          <div className="flex-shrink-0">
            <span className="text-4xl animate-pulse">⚠️</span>
          </div>
          
          <div className="flex-1">
            <h2 className="text-xl font-bold text-sentineldr-critical mb-2">
              DISASTER RECOVERY FAILOVER ACTIVE
            </h2>
            
            <div className="text-lg font-semibold text-sentineldr-warning mb-3">
              PRIMARY NODE OFFLINE
            </div>
            
            <div className="text-sentineldr-text-primary space-y-2">
              <p>
                Phone recovery node is now serving the synchronized application state.
              </p>
              
              {failoverTime && (
                <p className="text-sm">
                  <span className="text-sentineldr-text-muted">Failover activated at:</span>{' '}
                  <span className="font-mono font-medium">
                    {formatTimestamp(failoverTime)}
                  </span>
                </p>
              )}
            </div>
          </div>
          
          <div className="flex-shrink-0">
            <NeumorphicButton
              label={acknowledged ? "Acknowledged" : "Acknowledge"}
              onClick={handleAcknowledge}
              loading={isAcknowledging}
              disabled={acknowledged}
              variant="danger"
              size="md"
            />
          </div>
        </div>
        
        {acknowledged && (
          <div className="mt-4 pt-4 border-t border-sentineldr-warning/20">
            <div className="flex items-center gap-2 text-sentineldr-success">
              <span>✅</span>
              <span className="text-sm font-medium">
                Alert acknowledged - Monitoring for primary node recovery
              </span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

