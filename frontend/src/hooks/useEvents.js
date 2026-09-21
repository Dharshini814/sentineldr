import { useState, useEffect, useRef, useCallback } from 'react';
import { eventsAPI } from '../api/events.js';

export function useEvents(limit = 50) {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);
  
  const fetchEvents = async () => {
    try {
      const eventsData = await eventsAPI.getEvents(limit);
      setEvents(Array.isArray(eventsData) ? eventsData : []);
      setError(null);
    } catch (err) {
      console.error('Events fetch failed:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };
  
  const acknowledge = useCallback(async (eventId) => {
    try {
      await eventsAPI.acknowledgeEvent(eventId);
      
      // Optimistically update the local state
      setEvents(prevEvents => 
        prevEvents.map(event => 
          event.id === eventId 
            ? { ...event, acknowledged: true }
            : event
        )
      );
      
      // Refresh to get the latest state
      setTimeout(fetchEvents, 500);
      
    } catch (err) {
      console.error('Event acknowledge failed:', err);
      // Refresh to get actual state
      fetchEvents();
    }
  }, []);
  
  const startPolling = () => {
    fetchEvents();
    intervalRef.current = setInterval(fetchEvents, 3000);
  };
  
  const stopPolling = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };
  
  const refresh = () => {
    setLoading(true);
    fetchEvents();
  };
  
  useEffect(() => {
    startPolling();
    
    return () => {
      stopPolling();
    };
  }, [limit]);
  
  // Derived data
  const unacknowledged = events.filter(event => !event.acknowledged);
  const criticalCount = events.filter(event => 
    event.severity?.toLowerCase() === 'critical' && !event.acknowledged
  ).length;
  
  return {
    events,
    unacknowledged,
    criticalCount,
    acknowledge,
    loading,
    error,
    refresh,
  };
}