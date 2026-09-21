import { api } from './client.js';

export const eventsAPI = {
  getEvents: (limit = 50) => api.get(`/events?limit=${limit}`),
  acknowledgeEvent: (id) => api.post(`/events/${id}/acknowledge`),
};