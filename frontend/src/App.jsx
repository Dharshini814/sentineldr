import React from 'react';
import { BrowserRouter as Router, Routes, Route, useLocation } from 'react-router-dom';
import { Sidebar } from './components/layout/Sidebar.jsx';
import { Header } from './components/layout/Header.jsx';
import Dashboard from './pages/Dashboard.jsx';
import Monitoring from './pages/Monitoring.jsx';
import Events from './pages/Events.jsx';
import Nodes from './pages/Nodes.jsx';
import Heartbeat from './pages/Heartbeat.jsx';
import Failover from './pages/Failover.jsx';
import Replication from './pages/Replication.jsx';
import Network from './pages/Network.jsx';
import Audit from './pages/Audit.jsx';
import Settings from './pages/Settings.jsx';
import { useHealth } from './hooks/useHealth.js';
import { useNodes } from './hooks/useNodes.js';

function App() {
  return (
    <Router>
      <div className="h-screen bg-sentineldr-bg-deep flex overflow-hidden">
        <AppContent />
      </div>
    </Router>
  );
}

function AppContent() {
  const location = useLocation();
  const { health, refresh: refreshHealth, loading: healthLoading } = useHealth();
  const { nodes, refresh: refreshNodes } = useNodes();
  
  const handleRefresh = () => {
    refreshHealth();
    refreshNodes();
  };
  
  const getPageTitle = (pathname) => {
    switch (pathname) {
      case '/': return 'Dashboard';
      case '/monitoring': return 'System Monitoring';
      case '/events': return 'Alerts & Events';
      case '/nodes': return 'Node Management';
      case '/heartbeat': return 'Heartbeat Monitoring';
      case '/failover': return 'Failover Control';
      case '/replication': return 'Data Replication';
      case '/network': return 'Network Monitoring';
      case '/audit': return 'Audit Logs';
      case '/security': return 'Security';
      case '/settings': return 'Settings';
      default: return 'SentinelDR';
    }
  };
  
  return (
    <>
      {/* Sidebar */}
      <Sidebar />
      
      {/* Main Content */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <Routes>
          <Route path="*" element={
            <Header 
              title={getPageTitle(location.pathname)}
              health={health}
              nodes={nodes}
              onRefresh={handleRefresh}
              loading={healthLoading}
            />
          } />
        </Routes>
        
        {/* Page Content */}
        <main className="flex-1 overflow-auto p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/monitoring" element={<Monitoring />} />
            <Route path="/events" element={<Events />} />
            <Route path="/nodes" element={<Nodes />} />
            <Route path="/heartbeat" element={<Heartbeat />} />
            <Route path="/failover" element={<Failover />} />
            <Route path="/replication" element={<Replication />} />
            <Route path="/network" element={<Network />} />
            <Route path="/audit" element={<Audit />} />
            <Route path="/security" element={<div className="text-center py-20 text-sentineldr-text-muted">🚧 Security page coming soon...</div>} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </>
  );
}

export default App;