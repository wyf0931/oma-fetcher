// Checkout page. Creates an order, forwards the buyer to Alipay, then polls
// `alipay.trade.query` (via the order endpoint) until the payment settles.
function payPage() {
  return {
    apiClient: window.apiClient,
    locale: (window.FetchlyI18n && window.FetchlyI18n.detectLocale()) || 'en',
    needsLogin: false,
    sku: null,
    state: 'ready', // ready | redirecting | paid
    credits: 0,
    error: '',
    orderId: null,
    pollTimer: null,
    pollAttempts: 0,

    async init() {
      document.documentElement.setAttribute('lang', this.locale);
      await this.loadCurrentUser();
      if (!this.needsLogin) await this.loadSku();
      this.$nextTick(() => window.lucide && lucide.createIcons());
    },

    // One stable idempotency key per (checkout session, SKU): a reload of the
    // same product never double-charges, but a different product gets its own.
    idempotencyKeyFor(skuCode) {
      const storeKey = 'fetchly.checkout.idem.' + skuCode;
      let key = '';
      try { key = sessionStorage.getItem(storeKey) || ''; } catch { /* ignore */ }
      if (!key) {
        key = (crypto.randomUUID && crypto.randomUUID()) || ('idem-' + Date.now() + '-' + Math.random().toString(36).slice(2));
        try { sessionStorage.setItem(storeKey, key); } catch { /* ignore */ }
      }
      return key;
    },

    loginHref() {
      // Preserve ?test=1 etc. so signing in returns to the same checkout variant.
      const query = window.location.search || '';
      return '/login.html?next=' + encodeURIComponent('/pay.html' + query);
    },

    async loadCurrentUser() {
      // Checkout always needs an account (orders/credits are per-user), even when
      // global API auth is off. Probe /api/auth/me directly; a logged-out visitor
      // is shown the sign-in prompt instead of being rejected at pay time.
      try {
        const me = await this.apiClient.auth.me();
        this.needsLogin = !(me.data && me.data.user);
      } catch {
        this.needsLogin = true;
      }
    },

    async loadSku() {
      try {
        // `?test=1` loads the hidden ¥0.10 sandbox smoke-test SKU (DEBUG only).
        const isTest = new URLSearchParams(window.location.search).get('test') === '1';
        const endpoint = isTest ? '/api/billing/test-sku' : '/api/billing/skus';
        const result = await this.apiClient.request(endpoint);
        if (isTest) {
          this.sku = result.data || null;
        } else {
          const skus = (result.data && result.data.skus) || [];
          this.sku = skus.find((s) => s.code === 'fetch-1000') || skus[0] || null;
        }
        if (!this.sku) this.error = this.$t('pay.error');
      } catch {
        this.error = this.$t('pay.error');
      }
    },

    async startPayment() {
      if (!this.sku) return;
      this.error = '';
      this.state = 'redirecting';
      try {
        // Key is scoped to the SKU so switching products never replays an old order.
        const idemKey = this.idempotencyKeyFor(this.sku.code);
        const result = await this.apiClient.request('/api/billing/orders', {
          method: 'POST',
          body: JSON.stringify({ sku_code: this.sku.code, quantity: 1, idempotency_key: idemKey }),
        });
        const order = result.data && result.data.order;
        const formHtml = result.data && result.data.payment_form_html;
        if (order) this.orderId = order.id;
        if (order && order.status === 'paid') { await this.markPaid(); return; }
        if (!formHtml) { this.error = this.$t('pay.error'); this.state = 'ready'; return; }
        // Parse Alipay's auto-submitting form with DOMParser: the result is an
        // inert document (no script execution, no requests), so adopting its
        // nodes is safe. Our backend HTML-escapes every attribute value and the
        // form contains only hidden inputs.
        const parsed = new DOMParser().parseFromString(formHtml, 'text/html');
        const form = parsed.querySelector('form');
        if (!form) { this.error = this.$t('pay.error'); this.state = 'ready'; return; }
        const adopted = document.adoptNode(form);
        document.body.appendChild(adopted);
        // Begin polling in case we regain focus after payment.
        this.startPolling();
        adopted.submit();
      } catch (e) {
        this.error = (e && e.message) || this.$t('pay.error');
        this.state = 'ready';
      }
    },

    startPolling() {
      if (this.pollTimer || !this.orderId) return;
      this.pollTimer = setInterval(() => this.checkOrder(), 2500);
    },

    async checkOrder() {
      if (!this.orderId) return;
      this.pollAttempts += 1;
      if (this.pollAttempts > 120) { clearInterval(this.pollTimer); return; } // ~5 min
      try {
        const result = await this.apiClient.request('/api/billing/orders/' + this.orderId);
        const order = result.data && result.data.order;
        if (order && order.status === 'paid') {
          this.credits = (result.data && result.data.credits) || 0;
          await this.markPaid();
        }
      } catch { /* keep polling */ }
    },

    async markPaid() {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
      try { sessionStorage.removeItem('fetchly.checkout.idem'); } catch { /* ignore */ }
      this.state = 'paid';
      this.$nextTick(() => window.lucide && lucide.createIcons());
    },
  };
}
window.payPage = payPage;
