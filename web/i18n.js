// Fetchly i18n — zero-dependency, Alpine-native internationalization.
// Fits the project stack: Alpine.js + Tailwind/daisyUI loaded via CDN, no build step.
//
// Usage in markup:  <span x-text="$t('nav.playground')"></span>
//                   <input :placeholder="$t('playground.urlPlaceholder')" />
// In component JS:  this.$t('toast.resultDeleted')
// Switch language:  this.setLocale('zh')  // persisted to localStorage
(function () {
  'use strict';

  var STORAGE_KEY = 'fetchly.locale';
  var SUPPORTED = ['en', 'zh'];

  var dictionaries = {
    en: {
      app: {
        title: 'Fetchly · Playground',
      },
      nav: {
        playground: 'Playground',
        results: 'Results',
        keys: 'API Keys',
        mcp: 'MCP config',
        mcpTitle: 'MCP server config',
        settings: 'Proxy settings',
        openMenu: 'Open navigation menu',
        language: 'Language',
      },
      playground: {
        title: 'Playground',
        subtitle: 'Run fetch and discovery requests against the live service.',
        request: 'Request',
        requestBuilder: 'Request builder',
        page: 'Page',
        robots: 'Robots',
        sitemap: 'Sitemap',
        targetUrl: 'Target URL',
        urlPlaceholder: 'https://example.com/article',
        outputFormat: 'Output format',
        markdown: 'Markdown',
        plainText: 'Plain text',
        json: 'JSON',
        xml: 'XML',
        strategy: 'Strategy',
        auto: 'Auto',
        timeout: 'Timeout (sec)',
        saveToResults: 'Save to Results',
        persistHint: 'Persist this page result',
        sendRequest: 'Send request',
        running: 'Running request…',
        usesSavedKey: 'Requests use the currently saved API key.',
        response: 'Response',
        body: 'Body',
        metadata: 'Metadata',
        error: 'Error',
        emptyTitle: 'Your response will appear here',
        emptyHint: 'Run a fetch or discovery request to inspect extracted content, strategy details, and fallback attempts.',
        copyBody: 'Copy response body',
        copyMeta: 'Copy response metadata',
        emptyBody: '(empty response body)',
        savedToResults: 'Saved to Results · ID',
      },
      results: {
        title: 'Results',
        subtitle: 'Browse results saved from the web.',
        searchLabel: 'Title or content',
        searchPlaceholder: 'Search saved results…',
        siteLabel: 'Site name',
        sitePlaceholder: 'Filter by site…',
        tagsLabel: 'Tags',
        tagsPlaceholder: 'Filter by tags…',
        search: 'Search',
        colTitle: 'Title',
        colSite: 'Site',
        colPublished: 'Published',
        colFetched: 'Fetched',
        colActions: 'Actions',
        noResults: 'No results found.',
        untitled: '(untitled)',
        open: 'Open result',
        delete: 'Delete result',
        pages: 'Results pages',
        previous: 'Previous page',
        next: 'Next page',
        page: 'Page {n}',
        total: '{n} total',
      },
      keys: {
        title: 'Keys',
        subtitle: 'Manage API keys for readers and agents.',
        new: 'New',
        colName: 'Name',
        colKey: 'Key',
        colScopes: 'Scopes',
        colCreated: 'Created',
        colStatus: 'Status',
        colActions: 'Actions',
        noKeys: 'No API keys found.',
        active: 'active',
        copyToken: 'Copy token',
        delete: 'Delete key',
      },
      auth: {
        title: 'Connect to Fetchly',
        description: 'Enter an API key to access this service. It stays in this browser\'s local storage.',
        tokenPlaceholder: 'Bearer token',
        continue: 'Continue',
      },
      keyDialog: {
        title: 'Create API key',
        description: 'Give the key a name for this reader or agent.',
        namePlaceholder: 'Name, e.g. temporary-reader',
        cancel: 'Cancel',
        create: 'Create',
      },
      detail: {
        close: 'Close result',
        body: 'Body',
        metadata: 'Metadata',
        copyBody: 'Copy result body',
        copyMeta: 'Copy result metadata',
        untitled: '(untitled)',
      },
      mcp: {
        title: 'MCP server',
        description: 'Connect any MCP client to this running instance over Streamable HTTP.',
        close: 'Close MCP config',
        copyConfig: 'Copy MCP config',
        closeAction: 'Close',
        toolsLabel: 'Tools:',
        authHint: 'Set FETCHLY_API_TOKEN in your MCP client environment, or paste a token in place of the placeholder. When API_AUTH_ENABLED=off, the headers block can be omitted. See docs/mcp.md for stdio config.',
      },
      proxy: {
        title: 'Proxy settings',
        description: 'Configure the outbound proxy used by page, robots.txt, and sitemap requests.',
        close: 'Close proxy settings',
        useProxy: 'Use proxy',
        enableProxy: 'Enable outbound proxy',
        envLoadedNotApplied: 'Environment configuration loaded · not applied',
        savedOverride: 'Saved Web UI override',
        usingEnvironment: 'Using environment configuration',
        scheme: 'Scheme',
        server: 'Server',
        port: 'Port',
        username: 'Username',
        password: 'Password',
        savedUsername: 'Saved username (leave blank to keep)',
        savedPassword: 'Saved password (leave blank to keep)',
        optional: 'Optional',
        removeCredentials: 'Remove saved credentials',
        credentialsNote: 'Credentials are stored on this service and never sent back to the browser.',
        useEnvironment: 'Use environment',
        closeAction: 'Close',
        save: 'Save',
      },
      toast: {
        resultDeleted: 'Result deleted',
        keyCreated: 'API key created; use Copy in the table',
        keyDeleted: 'API key deleted',
        proxyApplied: 'Environment proxy settings applied',
        proxySaved: 'Proxy settings saved and applied',
        envLoaded: 'Environment settings loaded; save to apply',
        copied: 'Copied to clipboard',
        clipboardUnavailable: 'Clipboard unavailable; copy the text manually',
        apiKeySaved: 'API key saved',
        requestFailed: 'Request failed',
      },
      account: {
        menuTitle: 'Account',
        signIn: 'Sign in',
        signOut: 'Sign out',
        createAccount: 'Create account',
        register: 'Register',
        loginTitle: 'Sign in',
        registerTitle: 'Create account',
        description: 'Use an account to keep your results and API keys private to you.',
        email: 'Email',
        emailPlaceholder: 'you@example.com',
        displayName: 'Display name',
        displayNamePlaceholder: 'Optional',
        password: 'Password',
        passwordPlaceholder: '••••••••',
        cancel: 'Cancel',
        submitLogin: 'Sign in',
        submitRegister: 'Create account',
        created: 'Account created',
        signedIn: 'Signed in',
        signedOut: 'Signed out',
        failed: 'Authentication failed',
      },
      confirm: {
        deleteResult: 'Delete this result and its fetch history?',
        deleteKey: 'Delete this API key permanently?',
      },
    },

    zh: {
      app: {
        title: 'Fetchly · 试用场',
      },
      nav: {
        playground: '试用场',
        results: '抓取结果',
        keys: 'API 密钥',
        mcp: 'MCP 配置',
        mcpTitle: 'MCP 服务器配置',
        settings: '代理设置',
        openMenu: '打开导航菜单',
        language: '语言',
      },
      playground: {
        title: '试用场',
        subtitle: '对运行中的服务发起抓取与发现请求。',
        request: '请求',
        requestBuilder: '请求构建器',
        page: '网页',
        robots: 'Robots',
        sitemap: '站点地图',
        targetUrl: '目标 URL',
        urlPlaceholder: 'https://example.com/article',
        outputFormat: '输出格式',
        markdown: 'Markdown',
        plainText: '纯文本',
        json: 'JSON',
        xml: 'XML',
        strategy: '抓取策略',
        auto: '自动',
        timeout: '超时（秒）',
        saveToResults: '保存到抓取结果',
        persistHint: '持久化保存该网页结果',
        sendRequest: '发送请求',
        running: '正在请求…',
        usesSavedKey: '请求将使用当前已保存的 API 密钥。',
        response: '响应',
        body: '正文',
        metadata: '元数据',
        error: '错误',
        emptyTitle: '响应内容将显示在这里',
        emptyHint: '发起一次抓取或发现请求，查看提取的内容、策略细节与降级尝试。',
        copyBody: '复制响应正文',
        copyMeta: '复制响应元数据',
        emptyBody: '（空响应正文）',
        savedToResults: '已保存到抓取结果 · ID',
      },
      results: {
        title: '抓取结果',
        subtitle: '浏览从网页保存的抓取结果。',
        searchLabel: '标题或内容',
        searchPlaceholder: '搜索已保存的结果…',
        siteLabel: '站点名称',
        sitePlaceholder: '按站点筛选…',
        tagsLabel: '标签',
        tagsPlaceholder: '按标签筛选…',
        search: '搜索',
        colTitle: '标题',
        colSite: '站点',
        colPublished: '发布时间',
        colFetched: '抓取时间',
        colActions: '操作',
        noResults: '未找到结果。',
        untitled: '（无标题）',
        open: '打开结果',
        delete: '删除结果',
        pages: '结果分页',
        previous: '上一页',
        next: '下一页',
        page: '第 {n} 页',
        total: '共 {n} 条',
      },
      keys: {
        title: '密钥',
        subtitle: '管理供阅读器与智能体使用的 API 密钥。',
        new: '新建',
        colName: '名称',
        colKey: '密钥',
        colScopes: '权限范围',
        colCreated: '创建时间',
        colStatus: '状态',
        colActions: '操作',
        noKeys: '未找到 API 密钥。',
        active: '启用',
        copyToken: '复制令牌',
        delete: '删除密钥',
      },
      auth: {
        title: '连接到 Fetchly',
        description: '输入 API 密钥以访问本服务。密钥仅保存在当前浏览器的本地存储中。',
        tokenPlaceholder: 'Bearer 令牌',
        continue: '继续',
      },
      keyDialog: {
        title: '创建 API 密钥',
        description: '为该阅读器或智能体的密钥取一个名称。',
        namePlaceholder: '名称，例如 temporary-reader',
        cancel: '取消',
        create: '创建',
      },
      detail: {
        close: '关闭结果',
        body: '正文',
        metadata: '元数据',
        copyBody: '复制结果正文',
        copyMeta: '复制结果元数据',
        untitled: '（无标题）',
      },
      mcp: {
        title: 'MCP 服务器',
        description: '通过 Streamable HTTP 将任意 MCP 客户端连接到本运行实例。',
        close: '关闭 MCP 配置',
        copyConfig: '复制 MCP 配置',
        closeAction: '关闭',
        toolsLabel: '工具：',
        authHint: '在 MCP 客户端环境中设置 FETCHLY_API_TOKEN，或用令牌替换占位符。当 API_AUTH_ENABLED=off 时，可省略 headers 配置块。stdio 配置参见 docs/mcp.md。',
      },
      proxy: {
        title: '代理设置',
        description: '配置网页、robots.txt 与站点地图请求所使用的出站代理。',
        close: '关闭代理设置',
        useProxy: '启用代理',
        enableProxy: '启用出站代理',
        envLoadedNotApplied: '已加载环境配置 · 未应用',
        savedOverride: '已保存的网页界面覆盖配置',
        usingEnvironment: '正在使用环境配置',
        scheme: '协议',
        server: '服务器',
        port: '端口',
        username: '用户名',
        password: '密码',
        savedUsername: '已保存用户名（留空则保留）',
        savedPassword: '已保存密码（留空则保留）',
        optional: '可选',
        removeCredentials: '移除已保存的凭据',
        credentialsNote: '凭据仅存储在本服务上，绝不会回传给浏览器。',
        useEnvironment: '使用环境配置',
        closeAction: '关闭',
        save: '保存',
      },
      toast: {
        resultDeleted: '结果已删除',
        keyCreated: 'API 密钥已创建，请在表格中使用复制',
        keyDeleted: 'API 密钥已删除',
        proxyApplied: '环境代理设置已应用',
        proxySaved: '代理设置已保存并应用',
        envLoaded: '已加载环境设置，请保存以应用',
        copied: '已复制到剪贴板',
        clipboardUnavailable: '剪贴板不可用，请手动复制文本',
        apiKeySaved: 'API 密钥已保存',
        requestFailed: '请求失败',
      },
      account: {
        menuTitle: '账户',
        signIn: '登录',
        signOut: '退出登录',
        createAccount: '创建账户',
        register: '注册',
        loginTitle: '登录',
        registerTitle: '创建账户',
        description: '使用账户可将你的结果与 API 密钥设为仅自己可见。',
        email: '邮箱',
        emailPlaceholder: 'you@example.com',
        displayName: '显示名称',
        displayNamePlaceholder: '可选',
        password: '密码',
        passwordPlaceholder: '••••••••',
        cancel: '取消',
        submitLogin: '登录',
        submitRegister: '创建账户',
        created: '账户已创建',
        signedIn: '已登录',
        signedOut: '已退出登录',
        failed: '认证失败',
      },
      confirm: {
        deleteResult: '删除该结果及其抓取历史？',
        deleteKey: '永久删除该 API 密钥？',
      },
    },
  };

  function detectLocale() {
    var stored = null;
    try { stored = window.localStorage.getItem(STORAGE_KEY); } catch { /* ignore */ }
    if (stored && SUPPORTED.indexOf(stored) !== -1) return stored;
    var nav = (navigator.languages && navigator.languages[0]) || navigator.language || 'en';
    nav = String(nav).toLowerCase();
    if (nav.indexOf('zh') === 0) return 'zh';
    return 'en';
  }

  function interpolate(template, params) {
    if (!params) return template;
    return template.replace(/\{(\w+)\}/g, function (match, name) {
      return Object.prototype.hasOwnProperty.call(params, name) ? params[name] : match;
    });
  }

  function lookup(dict, key) {
    return key.split('.').reduce(function (node, part) {
      return node && node[part] !== undefined ? node[part] : undefined;
    }, dict);
  }

  window.FetchlyI18n = {
    dictionaries: dictionaries,
    supported: SUPPORTED,
    detectLocale: detectLocale,
    STORAGE_KEY: STORAGE_KEY,

    // Resolve a dotted key against a locale dictionary, falling back to English,
    // then to the raw key so missing translations are visible rather than blank.
    translate: function (locale, key, params) {
      var dict = dictionaries[locale] || dictionaries.en;
      var value = lookup(dict, key);
      if (value === undefined) value = lookup(dictionaries.en, key);
      if (value === undefined) return key;
      return typeof value === 'string' ? interpolate(value, params) : value;
    },

    isSupported: function (locale) { return SUPPORTED.includes(locale); },
  };

  // Register reactive $t()/t locale magic. Alpine evaluates these inside its reactive
  // effect, so reading `locale` makes every translated string re-render on switch.
  // Loaded synchronously before Alpine (see index.html), so magic exists at Alpine boot.
  document.addEventListener('alpine:init', function () {
    if (!window.Alpine || !window.FetchlyI18n) return;
    Alpine.magic('t', function () {
      return function (key, params) {
        var scope = this;
        var locale = (scope && scope.locale) || window.FetchlyI18n.detectLocale();
        return window.FetchlyI18n.translate(locale, key, params);
      };
    });
    Alpine.magic('locale', function () {
      return (this && this.locale) || window.FetchlyI18n.detectLocale();
    });
  });
})();

// Expose for Node-based tooling/tests without a browser global (UMD-style export).
if (typeof module !== 'undefined' && module.exports) {
  module.exports = window.FetchlyI18n;
}
