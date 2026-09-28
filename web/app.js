function app() {
  return {
    apiClient: window.apiClient, view: 'playground', documents: [], keys: [], loading: false, keysLoading: false,
    filters: {content: '', sitename: '', tags: ''}, pagination: {page: 1, page_size: 20, total: 0, pages: 0},
    detail: null, detailDialog: false, showAuthDialog: false, authInput: '', showKeyDialog: false, newKeyName: '', tokenCache: {}, toast: '', toastType: 'success',
    playgroundMode: 'fetch', playground: {url: '', outputFormat: 'markdown', strategy: 'auto', timeout: 45, persist: false}, playgroundLoading: false, playgroundResponse: null, responseTab: 'body',
    async init() { window.addEventListener('oma-auth-required', () => { this.showAuthDialog = true; }); },
    navigate(view) { this.view = view; if (view === 'dataset') this.loadDocuments(1); if (view === 'keys') this.loadKeys(); },
    get playgroundMethod() { return this.playgroundMode === 'fetch' ? 'POST' : 'GET'; },
    setPlaygroundMode(mode) { this.playgroundMode = mode; this.playgroundResponse = null; this.responseTab = 'body'; this.$nextTick(() => lucide.createIcons()); },
    async runPlayground() {
      if (!this.playground.url || this.playgroundLoading) return;
      this.playgroundLoading = true;
      this.playgroundResponse = null;
      this.responseTab = 'body';
      const startedAt = performance.now();
      try {
        let path;
        let options = {};
        if (this.playgroundMode === 'fetch') {
          path = `/api/fetch${this.playground.persist ? '?persist=true' : ''}`;
          options = {method: 'POST', body: JSON.stringify({url: this.playground.url, output_format: this.playground.outputFormat, strategy: this.playground.strategy, timeout_seconds: Number(this.playground.timeout) || 45})};
        } else {
          path = `/api/${this.playgroundMode}?url=${encodeURIComponent(this.playground.url)}`;
        }
        const result = await this.apiClient.request(path, options);
        this.playgroundResponse = {ok: true, status: result.status, statusText: result.statusText, duration: Math.round(performance.now() - startedAt), data: typeof result.data === 'string' ? result.data : JSON.stringify(result.data, null, 2), meta: result.meta || {}};
      } catch (error) {
        const envelope = error.envelope;
        this.playgroundResponse = {ok: false, status: error.status, statusText: '', duration: Math.round(performance.now() - startedAt), data: envelope ? JSON.stringify({code: envelope.code, message: envelope.message, data: envelope.data ?? null}, null, 2) : (error.message || 'Request failed'), meta: envelope?.meta || {}};
        if (error.status === 401) this.showAuthDialog = true;
      } finally {
        this.playgroundLoading = false;
        this.$nextTick(() => lucide.createIcons());
      }
    },
    async loadDocuments(page = 1) { this.loading = true; try { const query = new URLSearchParams({page, page_size: 20}); Object.entries(this.filters).forEach(([k,v]) => v && query.set(k,v)); const result = await this.apiClient.request(`/api/documents?${query}`); this.documents = result.data || []; this.pagination = result.meta || this.pagination; } catch (error) { this.handleError(error); } finally { this.loading = false; this.$nextTick(() => lucide.createIcons()); } },
    resetFilters() { this.filters = {content: '', sitename: '', tags: ''}; this.loadDocuments(1); },
    async openDocument(id) { try { this.detail = (await this.apiClient.request(`/api/documents/${id}`)).data; this.detailDialog = true; this.$nextTick(() => lucide.createIcons()); } catch (error) { this.handleError(error); } },
    async deleteDocument(id) { if (!window.confirm('Delete this document and its fetch history?')) return; try { await this.apiClient.request(`/api/documents/${id}`, {method: 'DELETE'}); this.notify('Document deleted'); await this.loadDocuments(this.pagination.page); } catch (error) { this.handleError(error); } },
    async loadKeys() { this.keysLoading = true; try { this.keys = (await this.apiClient.request('/api/keys')).data || []; } catch (error) { this.handleError(error); } finally { this.keysLoading = false; this.$nextTick(() => lucide.createIcons()); } },
    async createKey() { try { const result = await this.apiClient.request('/api/keys', {method: 'POST', body: JSON.stringify({name: this.newKeyName.trim(), scopes: ['fetch', 'search']})}); this.apiClient.saveToken(result.data.id, result.data.token); this.newKeyName = ''; this.showKeyDialog = false; await this.loadKeys(); this.notify('API key created; use Copy in the table'); } catch (error) { this.handleError(error); } },
    async revokeKey(id) { if (!window.confirm('Delete this API key permanently?')) return; try { await this.apiClient.request(`/api/keys/${id}`, {method: 'DELETE'}); this.apiClient.removeToken(id); this.notify('API key deleted'); await this.loadKeys(); } catch (error) { this.handleError(error); } },
    tokenFor(id) { return this.apiClient.getToken(id); },
    maskedKey(key) { return key?.key_prefix ? `${key.key_prefix.slice(0, 4)}***${(key.key_suffix || key.key_prefix.slice(-4))}` : '••••••••'; },
    async copyToken(id) { const token = this.tokenFor(id); if (token) await this.copyText(token); },
    async copyText(text) { try { await navigator.clipboard.writeText(text); this.notify('Copied to clipboard'); } catch { this.notify('Clipboard unavailable; copy the token manually', 'error'); } },
    async copyContent() { if (this.detail?.content) await this.copyText(this.detail.content); },
    saveKey() { if (!this.authInput.trim()) return; this.apiClient.setKey(this.authInput); this.authInput = ''; this.showAuthDialog = false; this.notify('API key saved'); this.loadDocuments(1); },
    clearKey() { this.apiClient.clearKey(); this.notify('API key cleared'); },
    handleError(error) { if (error.status === 401) this.showAuthDialog = true; else this.notify(error.message || 'Request failed', 'error'); },
    notify(message, type = 'success') { this.toast = message; this.toastType = type; setTimeout(() => { this.toast = ''; }, 3200); },
    truncate(value) { return value.length > 20 ? `${value.slice(0, 20)}…` : value; },
    formatDate(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(); },
    paginationLabel() { const start = this.pagination.total ? (this.pagination.page - 1) * this.pagination.page_size + 1 : 0; const end = Math.min(this.pagination.page * this.pagination.page_size, this.pagination.total); return `${start}–${end} of ${this.pagination.total}`; },
  };
}
