import { api } from './client.js';

export const syncAPI = {
  getSyncStatus: () => api.get('/sync/status'),
  triggerSync: () => api.post('/sync/now'),
};