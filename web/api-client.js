window.apiClient = (() => {
  const storageKey = 'oma_fetcher_api_key';
  const baseUrl = (window.OMA_FETCHER_API_BASE || 'http://127.0.0.1:7890').replace(/\/$/, '');
  class ApiError extends Error { constructor(message, status, envelope) { super(message); this.status = status; this.envelope = envelope; } }
  async function request(path, options = {}) {
    const headers = new Headers(options.headers || {});
    const token = localStorage.getItem(storageKey);
    if (token) headers.set('Authorization', `Bearer ${token}`);
    if (options.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(`${baseUrl}${path}`, {...options, headers});
    let envelope; try { envelope = await response.json(); } catch { throw new ApiError(`HTTP ${response.status}`, response.status, null); }
    if (!response.ok || envelope.code !== 0) {
      if (response.status === 401 || envelope.code === 1001) window.dispatchEvent(new Event('oma-auth-required'));
      throw new ApiError(envelope.message || `HTTP ${response.status}`, response.status, envelope);
    }
    return {data: envelope.data, meta: envelope.meta, headers: response.headers};
  }
  const tokenStorageKey = 'oma_fetcher_key_tokens';
  const tokenCache = () => JSON.parse(localStorage.getItem(tokenStorageKey) || '{}');
  return { request, hasKey: () => !!localStorage.getItem(storageKey), getKey: () => localStorage.getItem(storageKey), setKey: (key) => localStorage.setItem(storageKey, key.trim()), clearKey: () => localStorage.removeItem(storageKey), getToken: (id) => tokenCache()[id] || null, saveToken: (id, token) => { const cache = tokenCache(); cache[id] = token; localStorage.setItem(tokenStorageKey, JSON.stringify(cache)); }, removeToken: (id) => { const cache = tokenCache(); delete cache[id]; localStorage.setItem(tokenStorageKey, JSON.stringify(cache)); }, ApiError };
})();
