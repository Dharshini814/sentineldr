import { useState, useEffect, useRef } from 'react';
import { healthAPI } from '../api/health.js';
import { phoneAPI } from '../api/phoneClient.js';

export function useHealth() {
  const [health, setHealth] = useState(null);
  const [phoneHealth, setPhoneHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);
  const previousFailoverState = useRef(null);

  const fetchHealth = async () => {
    try {
      console.log('🔄 Fetching health data...');
      
      // Poll laptop (primary) and phone (secondary) concurrently.
      const [healthData, phoneData] = await Promise.all([
        healthAPI.getHealth().catch((err) => {
          console.error('❌ Laptop health fetch failed:', err.message);
          return null;
        }),
        phoneAPI.getHealth().catch((err) => {
          console.error('❌ Phone health fetch failed:', err.message);
          console.log('📱 Current phone URL:', phoneAPI.getCurrentPhoneUrl());
          return null;
        }),
      ]);

      let hasData = false;

      if (healthData) {
        console.log('✅ Laptop health data:', healthData);
        setHealth(healthData);
        hasData = true;
      } else {
        console.warn('⚠️ Laptop unreachable — set explicit offline status');
        // Laptop unreachable — set explicit offline status
        setHealth(null);
      }

      if (phoneData) {
        console.log('✅ Phone health data:', phoneData);
        setPhoneHealth(phoneData);
        hasData = true;
      } else {
        console.warn('⚠️ Phone unreachable — set explicit offline status');
        // Phone unreachable — set explicit offline status
        setPhoneHealth(null);
      }

      // Clear error if we got any data
      if (hasData) {
        setError(null);
      } else {
        setError('Both nodes unreachable');
      }

      // Determine true failover state: phone says so, OR laptop says so
      const laptopFailover = healthData?.failover_active || false;
      const phoneFailover = phoneData?.failover_active || false;
      const isFailover = laptopFailover || phoneFailover;

      // Detect state transitions for console logging
      if (previousFailoverState.current !== null) {
        const wasFailover = previousFailoverState.current;
        if (!wasFailover && isFailover) {
          console.warn('[SentinelDR] FAILOVER ACTIVATED');
        } else if (wasFailover && !isFailover) {
          console.info('[SentinelDR] FAILOVER RESOLVED — primary restored');
        }
      }
      previousFailoverState.current = isFailover;

    } catch (err) {
      console.error('Health check failed:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const startPolling = () => {
    fetchHealth();
    intervalRef.current = setInterval(fetchHealth, 3000);
  };

  const stopPolling = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  const refresh = () => {
    setLoading(true);
    fetchHealth();
  };

  useEffect(() => {
    startPolling();
    return () => stopPolling();
  }, []);

  // True failover: either node reports it (and that node is reachable)
  const isFailoverActive =
    (health?.failover_active) || 
    (phoneHealth?.failover_active) || 
    false;

  return {
    health,
    phoneHealth,
    loading,
    error,
    refresh,
    isFailoverActive,
    isHealthy: health?.status === 'healthy',
  };
}
