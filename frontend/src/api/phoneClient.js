// Phone node API client — polls the secondary node directly.
// Now with dynamic discovery: asks laptop server where phone is located

import { api } from './client.js';

let PHONE_URL = import.meta.env.VITE_PHONE_API_URL || 'http://localhost:8001';
let lastDiscoveryCheck = 0;
const DISCOVERY_INTERVAL = 10000; // Check every 10 seconds

async function discoverPhoneServer() {
    const now = Date.now();
    if (now - lastDiscoveryCheck < DISCOVERY_INTERVAL) {
        return; // Don't check too frequently
    }
    
    try {
        console.log('🔍 Discovering phone server location...');
        const response = await api.get('/phone-server-url');
        
        if (response.phone_server_url && response.status === 'discovered') {
            const newUrl = response.phone_server_url;
            if (PHONE_URL !== newUrl) {
                console.log(`📱 Phone server discovered at: ${newUrl} (was: ${PHONE_URL})`);
                PHONE_URL = newUrl;
            }
        } else {
            console.log('📱 Phone server not yet discovered by laptop server');
        }
        
        lastDiscoveryCheck = now;
    } catch (error) {
        console.warn('Failed to discover phone server:', error.message);
        lastDiscoveryCheck = now;
    }
}

async function phoneRequest(path) {
    // Try to discover phone server before making request
    await discoverPhoneServer();
    
    const API_KEY = import.meta.env.VITE_API_KEY;
    const headers = {};
    if (API_KEY && path !== '/health') {
        headers['X-API-Key'] = API_KEY;
    }
    
    try {
        console.log(`📱 Phone API request: ${PHONE_URL}${path}`);
        const response = await fetch(`${PHONE_URL}${path}`, { 
            headers,
            timeout: 5000 // 5 second timeout
        });
        
        if (!response.ok) {
            console.error(`📱 Phone API error: ${response.status}`);
            return null;
        }
        
        const ct = response.headers.get('content-type');
        if (ct && ct.includes('application/json')) {
            const data = await response.json();
            console.log(`📱 Phone API success: ${path}`, data);
            return data;
        }
        return null;
    } catch (error) {
        console.error(`📱 Phone API failed (${PHONE_URL}${path}):`, error.message);
        return null;
    }
}

export const phoneAPI = {
    getHealth: () => phoneRequest('/health'),
    getStatus: () => phoneRequest('/status'),
    getCurrentPhoneUrl: () => PHONE_URL,
};
