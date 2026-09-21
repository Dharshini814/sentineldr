import { useState, useEffect, useRef } from 'react';
import { nodesAPI } from '../api/nodes.js';

export function useNodes() {
  const [nodes, setNodes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const intervalRef = useRef(null);
  
  const fetchNodes = async () => {
    try {
      // Try to get nodes from primary first, then fallback to phone if primary is down
      let nodesData = null;
      
      try {
        nodesData = await nodesAPI.getNodes();
      } catch (primaryError) {
        // Primary is down, try to get data from phone server
        try {
          const response = await fetch('http://localhost:8001/nodes', {
            headers: {
              'X-API-Key': import.meta.env.VITE_API_KEY || 'demo-key'
            }
          });
          if (response.ok) {
            nodesData = await response.json();
          }
        } catch (phoneError) {
          throw primaryError; // Throw original error if both fail
        }
      }
      
      setNodes(Array.isArray(nodesData) ? nodesData : []);
      setError(null);
    } catch (err) {
      console.error('Nodes fetch failed:', err);
      setError(err.message);
      // Don't clear nodes on temporary failure - keep last known state for better UX
      // Only clear if we've never had data
      if (nodes.length === 0) {
        setNodes([]);
      }
    } finally {
      setLoading(false);
    }
  };
  
  const startPolling = () => {
    fetchNodes();
    intervalRef.current = setInterval(fetchNodes, 3000);
  };
  
  const stopPolling = () => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };
  
  const refresh = () => {
    setLoading(true);
    fetchNodes();
  };
  
  useEffect(() => {
    startPolling();
    
    return () => {
      stopPolling();
    };
  }, []);
  
  // Derived data - show nodes based on what's actually reachable
  const primaryNode = nodes.find(node => 
    node.role === 'primary' || node.role === 'laptop'
  );
  
  const secondaryNode = nodes.find(node => 
    (node.role === 'secondary' || node.role === 'active_secondary' || node.role === 'phone')
  );

  return {
    nodes,
    primaryNode: primaryNode || null,
    secondaryNode: secondaryNode || null,
    loading,
    error,
    refresh,
  };
}