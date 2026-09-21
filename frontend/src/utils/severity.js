export function getSeverityColor(severity) {
  const colors = {
    'critical': 'text-sentineldr-critical',
    'warning': 'text-sentineldr-warning', 
    'success': 'text-sentineldr-success',
    'info': 'text-sentineldr-info',
  };
  return colors[severity?.toLowerCase()] || 'text-sentineldr-text-secondary';
}

export function getSeverityBorder(severity) {
  const borders = {
    'critical': 'border-l-sentineldr-critical',
    'warning': 'border-l-sentineldr-warning',
    'success': 'border-l-sentineldr-success', 
    'info': 'border-l-sentineldr-info',
  };
  return borders[severity?.toLowerCase()] || 'border-l-sentineldr-text-muted';
}

export function getSeverityBadgeClass(severity) {
  const badges = {
    'critical': 'bg-sentineldr-critical/20 text-sentineldr-critical border-sentineldr-critical/30',
    'warning': 'bg-sentineldr-warning/20 text-sentineldr-warning border-sentineldr-warning/30',
    'success': 'bg-sentineldr-success/20 text-sentineldr-success border-sentineldr-success/30',
    'info': 'bg-sentineldr-info/20 text-sentineldr-info border-sentineldr-info/30',
  };
  return badges[severity?.toLowerCase()] || 'bg-sentineldr-bg-raised text-sentineldr-text-muted border-sentineldr-text-muted/30';
}

export function getSeverityIcon(severity) {
  const icons = {
    'critical': '🚨',
    'warning': '⚠️',
    'success': '✅',
    'info': 'ℹ️',
  };
  return icons[severity?.toLowerCase()] || '📋';
}

export function getStatusColor(status) {
  const colors = {
    'healthy': 'text-sentineldr-success',
    'online': 'text-sentineldr-success',
    'offline': 'text-sentineldr-critical',
    'degraded': 'text-sentineldr-warning',
    'unknown': 'text-sentineldr-text-muted',
  };
  return colors[status?.toLowerCase()] || 'text-sentineldr-text-muted';
}

export function getNodeRoleColor(role) {
  const colors = {
    'primary': 'text-sentineldr-purple-light bg-sentineldr-purple-primary/20 border-sentineldr-purple-primary/30',
    'secondary': 'text-sentineldr-text-secondary bg-sentineldr-bg-raised border-sentineldr-text-muted/30',
    'active_secondary': 'text-sentineldr-warning bg-sentineldr-warning/20 border-sentineldr-warning/30',
  };
  return colors[role?.toLowerCase()] || 'text-sentineldr-text-muted bg-sentineldr-bg-raised border-sentineldr-text-muted/30';
}

export function getSystemStatus(health, nodes) {
  if (!health && (!nodes || nodes.length === 0)) {
    return { status: 'OFFLINE', color: 'text-sentineldr-critical' };
  }
  
  if (health?.failover_active) {
    return { status: 'FAILOVER ACTIVE', color: 'text-sentineldr-warning' };
  }
  
  if (health?.status === 'healthy') {
    return { status: 'SYSTEM OK', color: 'text-sentineldr-success' };
  }
  
  return { status: 'DEGRADED', color: 'text-sentineldr-warning' };
}