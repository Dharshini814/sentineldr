import { api } from './client.js';

export const nodesAPI = {
  getNodes: () => api.get('/nodes'),
  getNode: (id) => api.get(`/nodes/${id}`),
};