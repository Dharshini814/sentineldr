import { api } from './client.js';

export const healthAPI = {
  getHealth: () => api.get('/health'),
};