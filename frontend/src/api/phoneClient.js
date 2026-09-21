// Phone node API client — polls the secondary node directly.
// Used to detect failover state that the phone reports but the laptop cannot.

const PHONE_URL = import.meta.env.VITE_PHONE_API_URL || 'http://localhost:8001';
const API_KEY = import.meta.env.VITE_API_KEY;

async function phoneRequest(path) {
  const headers = {};
  if (API_KEY && path !== '/health') {
    headers['X-API-Key'] = API_KEY;
  }
  try {
    const response = await fetch(`${PHONE_URL}${path}`, { headers });
    if (!response.ok) return null;
    const ct = response.headers.get('content-type');
    if (ct && ct.includes('application/json')) return await response.json();
    return null;
  } catch {
    return null;
  }
}

export const phoneAPI = {
  getHealth: () => phoneRequest('/health'),
  getStatus: () => phoneRequest('/status'),
};
