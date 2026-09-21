import { useState, useEffect, useRef, useCallback } from 'react';
import { syncAPI } from '../api/sync.js';

export function useSync() {
  const [syncStatus, setSyncStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const intervalRef = useRef(null);
  
  const fetchSyncStatus = async () => {
    try {
      const data = await syncAPI.getSyncStatus();
      setSyncStatus(data);
      setError(null);
    } catch (err) {
      console.error('Sync status fetch failed:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  
  const triggerSync = useCallback(async () => {
    setTriggerLoading(true);
    try {
      await syncAPI.triggerSync();
      // Refresh status after triggering sync
      setTimeout(fetchSyncStatus, 1000);
    } catch (err) {
      console.error('Trigger sync failed:', err);
      setError(err.message);
    } finally {
      setTriggerLoading(false);
    }
  }, []);
  
  const startPolling = () => {
    fetchSyncStatus();
    intervalRef.current = setInterval(fetchSyncStatus, 5000);  // matches backend SYNC_INTERVAL (5s)
  };
  
  const stopPolling = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };
  
  const refresh = () => {
    setLoading(true);
    fetchSyncStatus();
  };
  
  useEffect(() => {
    startPolling();
    
    return () => {
      stopPolling();
    };
  }, []);
  
  return {
    syncStatus,
    triggerSync,
    loading: loading || triggerLoading,
    error,
    refresh,
  };
}