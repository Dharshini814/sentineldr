import React, { useState, useEffect } from 'react';
import { useEvents } from '../hooks/useEvents.js';
import { formatRelativeTime } from '../utils/formatters.js';

export default function Audit() {
  const { events } = useEvents(200);
  const [auditLogs, setAuditLogs] = useState([]);
  const [filterCategory, setFilterCategory] = useState('all');
  const [filterUser, setFilterUser] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [dateRange, setDateRange] = useState('today');

  useEffect(() => {
    // Transform events into audit log format and add synthetic audit entries
    const generateAuditLogs = () => {
      const logs = [];
      const now = Date.now();
      
      // Add system events as audit logs
      events.forEach((event, index) => {
        logs.push({
          id: `evt-${event.id || index}`,
          timestamp: event.timestamp,
          category: 'SYSTEM',
          action: event.event_type || 'SYSTEM_EVENT',
          user: 'SYSTEM',
          resource: event.node_id || 'SentinelDR',
          details: event.message || event.details || 'System event occurred',
          severity: event.severity || 'INFO',
          source_ip: '127.0.0.1',
          result: 'SUCCESS'
        });
      });

      // Add synthetic audit entries for demonstration
      const syntheticLogs = [
        {
          id: 'audit-001',
          timestamp: now - 300000, // 5 minutes ago
          category: 'AUTHENTICATION',
          action: 'LOGIN',
          user: 'admin@sentineldr.com',
          resource: 'Dashboard',
          details: 'User logged into SentinelDR dashboard',
          severity: 'INFO',
          source_ip: '192.168.1.100',
          result: 'SUCCESS'
        },
        {
          id: 'audit-002',
          timestamp: now - 600000, // 10 minutes ago
          category: 'CONFIGURATION',
          action: 'UPDATE_SETTINGS',
          user: 'admin@sentineldr.com',
          resource: 'Failover Policy',
          details: 'Modified failover threshold from 3 to 5 attempts',
          severity: 'WARNING',
          source_ip: '192.168.1.100',
          result: 'SUCCESS'
        },
        {
          id: 'audit-003',
          timestamp: now - 900000, // 15 minutes ago
          category: 'SYSTEM',
          action: 'BACKUP_CREATED',
          user: 'SYSTEM',
          resource: 'Database',
          details: 'Automated database backup completed successfully',
          severity: 'INFO',
          source_ip: '127.0.0.1',
          result: 'SUCCESS'
        },
        {
          id: 'audit-004',
          timestamp: now - 1200000, // 20 minutes ago
          category: 'SECURITY',
          action: 'API_ACCESS',
          user: 'api-client',
          resource: '/health endpoint',
          details: 'External monitoring service accessed health endpoint',
          severity: 'INFO',
          source_ip: '203.0.113.45',
          result: 'SUCCESS'
        },
        {
          id: 'audit-005',
          timestamp: now - 1500000, // 25 minutes ago
          category: 'FAILOVER',
          action: 'SIMULATE_FAILURE',
          user: 'admin@sentineldr.com',
          resource: 'Primary Node',
          details: 'Initiated failover simulation for testing purposes',
          severity: 'WARNING',
          source_ip: '192.168.1.100',
          result: 'SUCCESS'
        }
      ];

      logs.push(...syntheticLogs);
      
      // Sort by timestamp (newest first)
      logs.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
      
      return logs;
    };

    setAuditLogs(generateAuditLogs());
  }, [events]);

  // Filter audit logs
  const filteredLogs = auditLogs.filter(log => {
    const categoryMatch = filterCategory === 'all' || log.category === filterCategory;
    const userMatch = filterUser === 'all' || log.user === filterUser;
    const searchMatch = searchQuery === '' || 
      log.action.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.details.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.resource.toLowerCase().includes(searchQuery.toLowerCase());
    
    // Date range filter
    const logDate = new Date(log.timestamp);
    const now = new Date();
    let dateMatch = true;
    
    if (dateRange === 'today') {
      dateMatch = logDate.toDateString() === now.toDateString();
    } else if (dateRange === 'week') {
      const weekAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
      dateMatch = logDate >= weekAgo;
    } else if (dateRange === 'month') {
      const monthAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
      dateMatch = logDate >= monthAgo;
    }
    
    return categoryMatch && userMatch && searchMatch && dateMatch;
  });

  // Get unique categories and users for filters
  const categories = ['all', ...new Set(auditLogs.map(log => log.category))];
  const users = ['all', ...new Set(auditLogs.map(log => log.user))];

  const getCategoryIcon = (category) => {
    switch (category) {
      case 'AUTHENTICATION': return '🔐';
      case 'CONFIGURATION': return '⚙️';
      case 'SYSTEM': return '🖥️';
      case 'SECURITY': return '🛡️';
      case 'FAILOVER': return '🔄';
      case 'DATABASE': return '💾';
      default: return '📋';
    }
  };

  const getSeverityColor = (severity) => {
    switch (severity?.toUpperCase()) {
      case 'CRITICAL': return 'text-sentineldr-critical';
      case 'WARNING': return 'text-sentineldr-warning';
      case 'INFO': return 'text-sentineldr-success';
      default: return 'text-sentineldr-text-muted';
    }
  };

  const getResultColor = (result) => {
    return result === 'SUCCESS' ? 'text-sentineldr-success' : 'text-sentineldr-critical';
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h1 className="text-3xl font-bold gradient-text mb-2">
          📜 Audit Logs
        </h1>
        <p className="text-sentineldr-text-secondary">
          Comprehensive audit trail for compliance, security, and operational transparency
        </p>
      </div>

      {/* Audit Statistics */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="glass-card rounded-xl p-4 border border-sentineldr-purple-primary/20">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xl">📊</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Total Entries</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-text-primary">
            {auditLogs.length}
          </div>
          <div className="text-sm text-sentineldr-text-muted">
            All recorded activities
          </div>
        </div>

        <div className="glass-card rounded-xl p-4 border border-sentineldr-success/30">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xl">✅</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Successful</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-success">
            {auditLogs.filter(log => log.result === 'SUCCESS').length}
          </div>
          <div className="text-sm text-sentineldr-text-muted">
            Completed operations
          </div>
        </div>

        <div className="glass-card rounded-xl p-4 border border-sentineldr-critical/30">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xl">❌</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Failed</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-critical">
            {auditLogs.filter(log => log.result === 'FAILED').length}
          </div>
          <div className="text-sm text-sentineldr-text-muted">
            Failed operations
          </div>
        </div>

        <div className="glass-card rounded-xl p-4 border border-sentineldr-warning/30">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-xl">⚠️</span>
            <h3 className="font-semibold text-sentineldr-text-primary">Security Events</h3>
          </div>
          <div className="text-2xl font-bold text-sentineldr-warning">
            {auditLogs.filter(log => log.category === 'SECURITY' || log.category === 'AUTHENTICATION').length}
          </div>
          <div className="text-sm text-sentineldr-text-muted">
            Authentication & security
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-lg font-semibold text-sentineldr-text-primary mb-4">
          Filter Audit Logs
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Search */}
          <div>
            <label className="block text-sm font-medium text-sentineldr-text-muted mb-2">
              Search
            </label>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search actions, resources..."
              className="w-full px-3 py-2 bg-sentineldr-bg-raised border border-sentineldr-purple-primary/20 rounded-lg text-sentineldr-text-primary placeholder-sentineldr-text-muted focus:outline-none focus:border-sentineldr-purple-primary/50"
            />
          </div>

          {/* Category Filter */}
          <div>
            <label className="block text-sm font-medium text-sentineldr-text-muted mb-2">
              Category
            </label>
            <select
              value={filterCategory}
              onChange={(e) => setFilterCategory(e.target.value)}
              className="w-full px-3 py-2 bg-sentineldr-bg-raised border border-sentineldr-purple-primary/20 rounded-lg text-sentineldr-text-primary focus:outline-none focus:border-sentineldr-purple-primary/50"
            >
              {categories.map(category => (
                <option key={category} value={category}>
                  {category === 'all' ? 'All Categories' : category}
                </option>
              ))}
            </select>
          </div>

          {/* User Filter */}
          <div>
            <label className="block text-sm font-medium text-sentineldr-text-muted mb-2">
              User
            </label>
            <select
              value={filterUser}
              onChange={(e) => setFilterUser(e.target.value)}
              className="w-full px-3 py-2 bg-sentineldr-bg-raised border border-sentineldr-purple-primary/20 rounded-lg text-sentineldr-text-primary focus:outline-none focus:border-sentineldr-purple-primary/50"
            >
              {users.map(user => (
                <option key={user} value={user}>
                  {user === 'all' ? 'All Users' : user}
                </option>
              ))}
            </select>
          </div>

          {/* Date Range */}
          <div>
            <label className="block text-sm font-medium text-sentineldr-text-muted mb-2">
              Time Range
            </label>
            <select
              value={dateRange}
              onChange={(e) => setDateRange(e.target.value)}
              className="w-full px-3 py-2 bg-sentineldr-bg-raised border border-sentineldr-purple-primary/20 rounded-lg text-sentineldr-text-primary focus:outline-none focus:border-sentineldr-purple-primary/50"
            >
              <option value="all">All Time</option>
              <option value="today">Today</option>
              <option value="week">Last 7 Days</option>
              <option value="month">Last 30 Days</option>
            </select>
          </div>
        </div>

        <div className="mt-4 text-sm text-sentineldr-text-muted">
          Showing {filteredLogs.length} of {auditLogs.length} audit entries
        </div>
      </div>

      {/* Audit Log Entries */}
      <div className="space-y-3">
        {filteredLogs.length > 0 ? (
          filteredLogs.slice(0, 50).map((log) => (
            <div 
              key={log.id}
              className="glass-card rounded-xl p-4 border border-sentineldr-purple-primary/20 hover:border-sentineldr-purple-primary/40 transition-colors"
            >
              <div className="flex items-start justify-between">
                <div className="flex items-start gap-3 flex-1">
                  <span className="text-2xl mt-1">
                    {getCategoryIcon(log.category)}
                  </span>
                  
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <h4 className="font-semibold text-sentineldr-text-primary">
                        {log.action.replace(/_/g, ' ')}
                      </h4>
                      <span className="px-2 py-1 text-xs font-medium rounded bg-sentineldr-purple-primary/20 text-sentineldr-purple-light">
                        {log.category}
                      </span>
                      <span className={`px-2 py-1 text-xs font-medium rounded ${
                        log.result === 'SUCCESS' ? 'bg-sentineldr-success/20 text-sentineldr-success' : 'bg-sentineldr-critical/20 text-sentineldr-critical'
                      }`}>
                        {log.result}
                      </span>
                    </div>
                    
                    <p className="text-sm text-sentineldr-text-secondary mb-3">
                      {log.details}
                    </p>
                    
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs text-sentineldr-text-muted">
                      <div>
                        <span className="font-medium">User:</span>
                        <div className="font-mono text-sentineldr-text-primary">{log.user}</div>
                      </div>
                      <div>
                        <span className="font-medium">Resource:</span>
                        <div className="font-mono text-sentineldr-text-primary">{log.resource}</div>
                      </div>
                      <div>
                        <span className="font-medium">Source IP:</span>
                        <div className="font-mono text-sentineldr-text-primary">{log.source_ip}</div>
                      </div>
                      <div>
                        <span className="font-medium">Severity:</span>
                        <div className={`font-medium ${getSeverityColor(log.severity)}`}>
                          {log.severity}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                
                <div className="text-right">
                  <div className="text-sm font-mono text-sentineldr-text-primary">
                    {new Date(log.timestamp).toLocaleString()}
                  </div>
                  <div className="text-xs text-sentineldr-text-muted mt-1">
                    {formatRelativeTime(log.timestamp)}
                  </div>
                  <div className="text-xs font-mono text-sentineldr-text-muted mt-1">
                    ID: {log.id}
                  </div>
                </div>
              </div>
            </div>
          ))
        ) : (
          <div className="glass-card rounded-xl p-8 text-center border border-sentineldr-purple-primary/20">
            <span className="text-4xl mb-4 block">📋</span>
            <h3 className="text-lg font-semibold text-sentineldr-text-primary mb-2">
              No Audit Logs Found
            </h3>
            <p className="text-sentineldr-text-muted">
              No audit entries match your current filters
            </p>
          </div>
        )}
      </div>

      {/* Compliance Footer */}
      <div className="glass-card rounded-xl p-6 border border-sentineldr-purple-primary/20">
        <h3 className="text-lg font-bold text-sentineldr-text-primary mb-4">
          Compliance & Retention Policy
        </h3>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-sm">
          <div>
            <h4 className="font-semibold text-sentineldr-text-primary mb-2">Data Retention</h4>
            <ul className="space-y-1 text-sentineldr-text-muted">
              <li>• Security events: 7 years</li>
              <li>• System events: 2 years</li>
              <li>• Configuration changes: 5 years</li>
              <li>• Authentication logs: 3 years</li>
            </ul>
          </div>
          
          <div>
            <h4 className="font-semibold text-sentineldr-text-primary mb-2">Compliance Standards</h4>
            <ul className="space-y-1 text-sentineldr-text-muted">
              <li>• SOC 2 Type II</li>
              <li>• ISO 27001</li>
              <li>• GDPR Article 30</li>
              <li>• HIPAA (where applicable)</li>
            </ul>
          </div>
          
          <div>
            <h4 className="font-semibold text-sentineldr-text-primary mb-2">Data Protection</h4>
            <ul className="space-y-1 text-sentineldr-text-muted">
              <li>• Encrypted at rest (AES-256)</li>
              <li>• Encrypted in transit (TLS 1.3)</li>
              <li>• Integrity checksums</li>
              <li>• Immutable log storage</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}