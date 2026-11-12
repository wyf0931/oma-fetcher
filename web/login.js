// Standalone login/register page. On success, returns the user to `?next=` (default "/").
function loginPage() {
  return {
    apiClient: window.apiClient,
    locale: (window.FetchlyI18n && window.FetchlyI18n.detectLocale()) || 'en',
    mode: 'login',
    email: '', password: '', displayName: '',
    loading: false, error: '',
    nextPath: '/',
    init() {
      document.documentElement.setAttribute('lang', this.locale);
      const params = new URLSearchParams(window.location.search);
      const next = params.get('next');
      // Only allow same-origin relative paths to avoid open-redirects.
      if (next && next.startsWith('/') && !next.startsWith('//')) this.nextPath = next;
      const mode = params.get('mode');
      if (mode === 'register') this.mode = 'register';
      this.$nextTick(() => window.lucide && lucide.createIcons());
    },
    backHref() { return this.nextPath || '/'; },
    async submit() {
      if (this.loading) return;
      this.loading = true; this.error = '';
      try {
        if (this.mode === 'register') {
          await this.apiClient.auth.register({ email: this.email, password: this.password, display_name: this.displayName || null });
        }
        await this.apiClient.auth.login({ email: this.email, password: this.password });
        window.location.assign(this.nextPath || '/');
      } catch (e) {
        this.error = e.message || 'Authentication failed';
        this.loading = false;
      }
    },
  };
}
window.loginPage = loginPage;
