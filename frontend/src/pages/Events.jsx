import React, { useState, useEffect } from 'react';
import { useEvents } from '../hooks/useEvents.js';
import { EventFeed } from '../components/EventFeed.jsx';
import { NeumorphicButton } from '../components/NeumorphicButton.jsx';
import { getSeverityIcon } from '../utils/severity.js';
import { formatRelativeTime } from '../utils/formatters.js';

export default function Events() {
  const { events, acknowledge, loading, error, refresh } = useEvents(100);
  const [severityFilter, setSeverityFilter] = useState('all');
  const [acknowledgedFilter, setAcknowledgedFilter] = useState('all');
  const [alertStats, setAlertStats] = useState({
    critical: 0,
    warning: 0,
    info: 0,
    total: 0,
    unacknowledged: 0
  });

  useEffect(() => {
    const stats = {
      critical: events.filter(e => e.severity?.toLowerCase() === 'critical').length,
      warning: events.filter(e => e.severity?.toLowerCase() === 'warning').length,
      info: events.filter(e => e.severity?.toLowerCase() === 'info').length,
      total: events.length,
      unacknowledged: events.filter(e => !e.acknowledged).length
    };
    setAlertStats(stats);
  }, [events]);

  const filteredEvents = events.filter(event => {
    const severityMatch = severityFilter === 'all' || 
      event.severity?.toLowerCase() === severityFilter.toLowerCase();
    
    const acknowledgedMatch = acknowledgedFilter === 'all' ||
      (acknowledgedFilter === 'unacknowledged' && !event.acknowledged) ||
      (acknowledgedFilter === 'acknowledged' && event.acknowledged);
    
    return severityMatch && acknowledgedMatch;
  });

  if (loading && events.length === 0) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-sentineldr-purple-primary border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <div className="text-sentineldr-text-secondary">Loading alerts...</div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <EventFeed
        events={filteredEvents}
        limit={50}
        onAcknowledge={acknowledge}
        className="min-h-[400px]"
      />
    </div>
  );
}