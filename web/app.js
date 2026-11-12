function app() {
  return {
    apiClient: window.apiClient, view: 'playground', documents: [], keys: [], loading: false, keysLoading: false,
    filters: {content: '', sitename: '', tags: ''}, pagination: {page: 1, page_size: 20, total: 0, pages: 0},
    detail: null, detailDialog: false, detailTab: 'body', showAuthDialog: false, authInput: '', showKeyDialog: false, newKeyName: '', tokenCache: {}, toast: '', toastType: 'success',
    currentUser: null,
    proxyDialog: false, proxyLoading: false, proxySaving: false, proxyUseEnvironment: false, proxyOriginalSnapshot: '', proxy: {enabled: false, scheme: 'http', server: '', port: '', username: '', password: '', clearCredentials: false, source: 'environment', usernameConfigured: false, passwordConfigured: false},
    playgroundMode: 'fetch', playground: {url: '', outputFormat: 'markdown', strategy: 'auto', timeout: 45, persist: false}, playgroundLoading: false, playgroundResponse: null, responseTab: 'body', showMcpDialog: false,
    locale: (window.FetchlyI18n && window.FetchlyI18n.detectLocale()) || 'en',
    supportedLocales: (window.FetchlyI18n && window.FetchlyI18n.supported) || ['en'],
    setLocale(locale) {
      if (!window.FetchlyI18n || !window.FetchlyI18n.isSupported(locale)) return;
      this.locale = locale;
      try { window.localStorage.setItem(window.FetchlyI18n.STORAGE_KEY, locale); } catch { /* ignore */ }
      document.documentElement.setAttribute('lang', locale);
      this.$nextTick(() => lucide.createIcons());
    },
    authEnabled: false,
    init() {
      document.documentElement.setAttribute('lang', this.locale);
      window.addEventListener('oma-auth-required', () => { this.showAuthDialog = true; });
      window.addEventListener('load', () => lucide.createIcons(), {once: true});
      this.loadCurrentUser(true);
    },
    loginHref() { const next = encodeURIComponent(window.location.pathname + window.location.search); return `/login?next=${next}`; },
    goToLogin() { window.location.assign(this.loginHref()); },
    navigate(view) { this.view = view; if (view === 'pages') this.loadDocuments(1); if (view === 'keys') this.loadKeys(); },
    get playgroundMethod() { return this.playgroundMode === 'fetch' ? 'POST' : 'GET'; },
    get mcpConfig() { return JSON.stringify({mcpServers: {fetchly: {type: 'http', url: `${window.location.origin}/mcp`, headers: {Authorization: 'Bearer ${FETCHLY_API_TOKEN}'}}}}, null, 2); },
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
        if (error.status === 401) this.openAuthFlow();
      } finally {
        this.playgroundLoading = false;
        this.$nextTick(() => lucide.createIcons());
      }
    },
    async loadDocuments(page = 1) { this.loading = true; try { const query = new URLSearchParams({page, page_size: 20}); Object.entries(this.filters).forEach(([k,v]) => v && query.set(k,v)); const result = await this.apiClient.request(`/api/documents?${query}`); this.documents = result.data || []; this.pagination = result.meta || this.pagination; } catch (error) { this.handleError(error); } finally { this.loading = false; this.$nextTick(() => lucide.createIcons()); } },
    async openDocument(id) { try { this.detail = (await this.apiClient.request(`/api/documents/${id}`)).data; this.detailTab = 'body'; this.detailDialog = true; this.$nextTick(() => lucide.createIcons()); } catch (error) { this.handleError(error); } },
    async deleteDocument(id) { if (!window.confirm(this.$t('confirm.deleteResult'))) return; try { await this.apiClient.request(`/api/documents/${id}`, {method: 'DELETE'}); this.notify(this.$t('toast.resultDeleted')); await this.loadDocuments(this.pagination.page); } catch (error) { this.handleError(error); } },
    async loadKeys() { this.keysLoading = true; try { this.keys = (await this.apiClient.request('/api/keys')).data || []; } catch (error) { this.handleError(error); } finally { this.keysLoading = false; this.$nextTick(() => lucide.createIcons()); } },
    async createKey() { try { const result = await this.apiClient.request('/api/keys', {method: 'POST', body: JSON.stringify({name: this.newKeyName.trim(), scopes: ['fetch', 'search']})}); this.apiClient.saveToken(result.data.id, result.data.token); this.newKeyName = ''; this.showKeyDialog = false; await this.loadKeys(); this.notify(this.$t('toast.keyCreated')); } catch (error) { this.handleError(error); } },
    async revokeKey(id) { if (!window.confirm(this.$t('confirm.deleteKey'))) return; try { await this.apiClient.request(`/api/keys/${id}`, {method: 'DELETE'}); this.apiClient.removeToken(id); this.notify(this.$t('toast.keyDeleted')); await this.loadKeys(); } catch (error) { this.handleError(error); } },
    async openProxySettings() {
      this.proxyDialog = true; this.proxyLoading = true;
      try {
        const result = await this.apiClient.request('/api/settings/proxy');
        const value = result.data || {};
        this.proxy = {...this.proxy, ...value, port: value.port ? String(value.port) : '', username: '', password: '', clearCredentials: false, usernameConfigured: value.username_configured, passwordConfigured: value.password_configured};
        this.proxyUseEnvironment = false;
        this.proxyOriginalSnapshot = this.proxySnapshot();
      } catch (error) { this.proxyDialog = false; this.handleError(error); }
      finally { this.proxyLoading = false; this.$nextTick(() => lucide.createIcons()); }
    },
    async saveProxySettings() {
      if (this.proxySaving || !this.proxyDirty) return;
      this.proxySaving = true;
      try {
        if (this.proxyUseEnvironment) {
          const result = await this.apiClient.request('/api/settings/proxy', {method: 'DELETE'});
          this.updateProxyForm(result.data);
          this.notify(this.$t('toast.proxyApplied'));
          return;
        }
        const payload = {enabled: this.proxy.enabled, scheme: this.proxy.scheme, server: this.proxy.server.trim(), port: this.proxy.port ? Number(this.proxy.port) : null, clear_credentials: this.proxy.clearCredentials};
        if (this.proxy.username) payload.username = this.proxy.username;
        if (this.proxy.password) payload.password = this.proxy.password;
        const result = await this.apiClient.request('/api/settings/proxy', {method: 'PUT', body: JSON.stringify(payload)});
        this.updateProxyForm(result.data);
        this.notify(this.$t('toast.proxySaved'));
      } catch (error) { this.handleError(error); }
      finally { this.proxySaving = false; }
    },
    proxySnapshot() {
      const {enabled, scheme, server, port, username, password, clearCredentials} = this.proxy;
      return JSON.stringify({enabled, scheme, server, port, username, password, clearCredentials});
    },
    get proxyDirty() { return this.proxyUseEnvironment || this.proxySnapshot() !== this.proxyOriginalSnapshot; },
    updateProxyForm(value) {
      this.proxy = {...this.proxy, ...value, port: value.port ? String(value.port) : '', username: '', password: '', clearCredentials: false, usernameConfigured: value.username_configured, passwordConfigured: value.password_configured};
      this.proxyUseEnvironment = false;
      this.proxyOriginalSnapshot = this.proxySnapshot();
    },
    async useEnvironmentProxy() {
      this.proxySaving = true;
      try {
        const result = await this.apiClient.request('/api/settings/proxy?source=environment');
        const value = result.data || {};
        this.proxy = {...this.proxy, ...value, source: 'environment-preview', port: value.port ? String(value.port) : '', username: '', password: '', clearCredentials: false, usernameConfigured: value.username_configured, passwordConfigured: value.password_configured};
        this.proxyUseEnvironment = true;
        this.notify(this.$t('toast.envLoaded'));
      }
      catch (error) { this.handleError(error); }
      finally { this.proxySaving = false; }
    },
    tokenFor(id) { return this.apiClient.getToken(id); },
    maskedKey(key) { return key?.key_prefix ? `${key.key_prefix.slice(0, 4)}***${(key.key_suffix || key.key_prefix.slice(-4))}` : '••••••••'; },
    async copyToken(id) { const token = this.tokenFor(id); if (token) await this.copyText(token); },
    async copyText(text) { try { await navigator.clipboard.writeText(text); this.notify(this.$t('toast.copied')); } catch { this.notify(this.$t('toast.clipboardUnavailable'), 'error'); } },
    formatJson(value) { return JSON.stringify(value ?? {}, null, 2) ?? 'null'; },
    highlightJson(value) {
      const source = this.formatJson(value);
      if (window.Prism?.languages?.json) return window.Prism.highlight(source, window.Prism.languages.json, 'json');
      return source.replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
    },
    async copyPlaygroundBlock() { const content = this.responseTab === 'body' ? this.playgroundResponse?.data || '(empty response body)' : JSON.stringify(this.playgroundResponse?.meta || {}, null, 2); if (content) await this.copyText(content); },
    async copyDetailBlock() { const content = this.detailTab === 'body' ? this.detail?.content : JSON.stringify(this.detail?.page || {}, null, 2); if (content) await this.copyText(content); },
    saveKey() { if (!this.authInput.trim()) return; this.apiClient.setKey(this.authInput); this.authInput = ''; this.showAuthDialog = false; this.notify(this.$t('toast.apiKeySaved')); this.loadDocuments(1); },
    openAccount(mode = 'login') { window.location.assign(`/login?mode=${mode}&next=${encodeURIComponent(window.location.pathname + window.location.search)}`); },
    async loadCurrentUser(promptOnLoggedOut = false) {
      // Learn whether the deployment requires accounts. When auth is off
      // (local/UAT), anonymous use is allowed and no login redirect happens.
      try { const status = await this.apiClient.request('/api/auth/status'); this.authEnabled = !!(status.data && status.data.auth_enabled); } catch { this.authEnabled = false; }
      try { const result = await this.apiClient.auth.me(); this.currentUser = result.data || null; } catch { this.currentUser = null; }
      if (promptOnLoggedOut && this.authEnabled && !this.currentUser) this.goToLogin();
    },
    async logoutAccount() { try { await this.apiClient.auth.logout(); } catch {} this.currentUser = null; this.notify(this.$t('account.signedOut')); if (this.authEnabled) this.goToLogin(); },
    handleError(error) { if (error.status === 401) this.openAuthFlow(); else this.notify(error.message || this.$t('toast.requestFailed'), 'error'); },
    // Route a 401 to the right destination: a logged-out visitor is sent to the
    // standalone sign-in page, while a logged-in caller lacking scope sees the
    // API-key dialog (their session can't grant the missing scope).
    openAuthFlow() { if (this.currentUser) { this.showAuthDialog = true; } else { this.goToLogin(); } },
    notify(message, type = 'success') { this.toast = message; this.toastType = type; setTimeout(() => { this.toast = ''; }, 3200); },
    truncate(value) { return value.length > 20 ? `${value.slice(0, 20)}…` : value; },
    formatDate(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(); },
    paginationLabel() { const start = this.pagination.total ? (this.pagination.page - 1) * this.pagination.page_size + 1 : 0; const end = Math.min(this.pagination.page * this.pagination.page_size, this.pagination.total); return `${start}–${end} · ${this.$t('results.total', {n: this.pagination.total})}`; },
    paginationPages() {
      const pages = Math.max(0, Number(this.pagination.pages) || 0);
      const current = Math.min(Math.max(1, Number(this.pagination.page) || 1), pages || 1);
      if (pages <= 5) return Array.from({length: pages}, (_, index) => index + 1);
      const start = Math.min(Math.max(1, current - 2), pages - 4);
      return Array.from({length: 5}, (_, index) => start + index);
    },
  };
}
