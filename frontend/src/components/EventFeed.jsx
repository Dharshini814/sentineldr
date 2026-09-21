import React, { useEffect, useRef } from 'react';
import { formatRelativeTime } from '../utils/formatters.js';
import { 
  getSeverityBorder, 
  getSeverityBadgeClass, 
  getSeverityIcon 
} from '../utils/severity.js';
import { NeumorphicButton } from './NeumorphicButton.jsx';

export function EventFeed({ 
  events = [], 
  limit = 10, 
  onAcknowledge,
  showActions = true,
  className = '' 
}) {
  const feedRef = useRef(null);
  const prevEventsLength = useRef(events.length);
  
  // Auto-scroll to newest event when new events arrive
  useEffect(() => {
    if (events.length > prevEventsLength.current && feedRef.current) {
      feedRef.current.scrollTop = 0;
    }
    prevEventsLength.current = events.length;
  }, [events.length]);
  
  const displayEvents = limit ? events.slice(0, limit) : events;
  
  if (displayEvents.length === 0) {
    return (
      <div className={`glass-card rounded-xl p-6 ${className}`}>
        <div className="text-center text-sentineldr-text-muted">
          <span className="text-2xl block mb-2">📋</span>
          <div>No events to display</div>
        </div>
      </div>
    );
  }
  
  return (
    <div className={`glass-card rounded-xl ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-sentineldr-purple-primary/20">
        <h3 className="font-semibold text-sentineldr-text-primary">
          Recent Events
          {limit && (
            <span className="ml-2 text-sm text-sentineldr-text-muted">
              (showing {displayEvents.length} of {events.length})
            </span>
          )}
        </h3>
      </div>
      
      {/* Event List */}
      <div 
        ref={feedRef}
        className="max-h-96 overflow-y-auto"
      >
        <div className="divide-y divide-sentineldr-purple-primary/10">
          {displayEvents.map((event, index) => (
            <EventRow 
              key={event.id || index}
              event={event}
              onAcknowledge={onAcknowledge}
              showActions={showActions}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function EventRow({ event, onAcknowledge, showActions }) {
  const severity = event.severity || 'info';
  const borderClass = getSeverityBorder(severity);
  const badgeClass = getSeverityBadgeClass(severity);
  const icon = getSeverityIcon(severity);
  
  const handleAcknowledge = () => {
    if (onAcknowledge && event.id) {
      onAcknowledge(event.id);
    }
  };
  
  return (
    <div className={`p-4 border-l-4 ${borderClass} hover:bg-sentineldr-bg-raised/30 transition-colors`}>
      <div className="flex items-start gap-3">
        {/* Severity Icon */}
        <span className="text-lg flex-shrink-0 mt-0.5">
          {icon}
        </span>
        
        {/* Event Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-3 mb-2">
            <div className="flex items-center gap-2 flex-wrap">
              {/* Severity Badge */}
              <span className={`px-2 py-1 text-xs font-medium rounded border ${badgeClass}`}>
                {severity.toUpperCase()}
              </span>
              
              {/* Event Type */}
              <span className="text-sm font-medium text-sentineldr-text-primary">
                {event.event_type || 'Unknown Event'}
              </span>
            </div>
            
            {/* Timestamp */}
            <span className="text-xs text-sentineldr-text-muted whitespace-nowrap">
              {formatRelativeTime(event.timestamp)}
            </span>
          </div>
          
          {/* Message */}
          <div className="text-sm text-sentineldr-text-secondary mb-2">
            {event.message}
          </div>
          
          {/* Source and Actions */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4 text-xs text-sentineldr-text-muted">
              {event.source && (
                <span>
                  <span className="font-medium">Source:</span> {event.source}
                </span>
              )}
              
              {event.acknowledged && (
                <span className="flex items-center gap-1 text-sentineldr-success">
                  ✅ <span>Acknowledged</span>
                </span>
              )}
            </div>
            
            {/* Acknowledge Button */}
            {showActions && !event.acknowledged && onAcknowledge && (
              <NeumorphicButton
                label="Acknowledge"
                onClick={handleAcknowledge}
                size="sm"
                variant="ghost"
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}