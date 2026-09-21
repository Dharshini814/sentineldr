const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_KEY = import.meta.env.VITE_API_KEY;

class APIError extends Error {
  constructor(message, status, response) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.response = response;
  }
}

async function request(method, path, body = null) {
  const url = `${BASE_URL}${path}`;
  
  const headers = {
    'Content-Type': 'application/json',
  };
  
  // Add API key if available and not the health endpoint
  if (API_KEY && path !== '/health') {
    headers['X-API-Key'] = API_KEY;
  }
  
  const config = {
    method,
    headers,
  };
  
  if (body) {
    config.body = JSON.stringify(body);
  }
  
  try {
    const response = await fetch(url, config);
    
    if (response.status === 401) {
      console.error('API Authentication failed - check VITE_API_KEY in .env');
      throw new APIError('Authentication failed', 401, response);
    }
    
    if (!response.ok) {
      const errorText = await response.text();
      throw new APIError(
        `HTTP ${response.status}: ${errorText}`,
        response.status,
        response
      );
    }
    
    // Handle empty responses
    const contentType = response.headers.get('content-type');
    if (contentType && contentType.includes('application/json')) {
      return await response.json();
    }
    
    return null;
  } catch (error) {
    if (error instanceof APIError) {
      throw error;
    }
    
    // Network or other errors
    console.error('API request failed:', error);
    throw new APIError(
      `Network error: ${error.message}`,
      0,
      null
    );
  }
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
  put: (path, body) => request('PUT', path, body),
  del: (path) => request('DELETE', path),
};

export { APIError };