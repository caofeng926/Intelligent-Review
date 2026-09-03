const { request } = require('../../utils/request');
const { setStorage, getStorage, removeStorage } = require('../../utils/storage');
const svgs = require('../../utils/svgs.js');

const TABS = [
  // kp(审核规则): /api/search 返回 { items, total, page, limit }
  // 代码表: /api/nhsa/<key>/search 返回 { count, q, results }
  // hc(耗材) 2026-09-03 新增: webapp/nhsa_api.py::_hc_search, FTS5 + LIKE 兜底
  { key: 'kp',  name: '审核规则', endpoint: '/api/search',           isCode: false },
  { key: 'yp',  name: '医保药品', endpoint: '/api/nhsa/yp/search',   isCode: true  },
  { key: 'hc',  name: '医用耗材', endpoint: '/api/nhsa/hc/search',   isCode: true  },
  { key: 'tcm', name: '中医病证', endpoint: '/api/nhsa/tcm/search',  isCode: true  },
  { key: 'icd', name: 'ICD-10',  endpoint: '/api/nhsa/icd/search',  isCode: true  },
  { key: 'ivd', name: '诊断试剂', endpoint: '/api/nhsa/ivd/search', isCode: true  },
  { key: 'ms',  name: '医疗服务', endpoint: '/api/nhsa/ms/search',   isCode: true  },
];

const HISTORY_KEY = 'search_history_v1';
const HISTORY_MAX = 12;

Page({
  data: {
    tabs: TABS,
    activeTab: 'kp',
    q: '',
    items: [],
    total: 0,
    loading: false,
    page: 1,
    pages: 1,
    isCode: false,
    searchIcon: svgs.search || '',
    xIcon: svgs.x || '',
    history: [],
    hotQueries: [],
  },

  onLoad(options) {
    const q = options.q ? decodeURIComponent(options.q) : '';
    const tab = options.tab && TABS.find(t => t.key === options.tab) ? options.tab : 'kp';
    const t = TABS.find(t => t.key === tab);
    this.setData({ q, activeTab: tab, isCode: t.isCode });
    this.loadHistory();
    this.loadHotQueries();
    if (q) this.doSearch(true);
  },

  async loadHotQueries() {
    try {
      const data = await request({ url: '/api/hot-queries', data: { limit: 8 }, silent: true });
      const items = (data && data.items) || [];
      this.setData({ hotQueries: items.map(i => i.q) });
    } catch (e) {
      this.setData({ hotQueries: [] });
    }
  },

  loadHistory() {
    const history = getStorage(HISTORY_KEY) || [];
    this.setData({ history });
  },

  saveHistory(q) {
    let history = getStorage(HISTORY_KEY) || [];
    history = [q, ...history.filter(x => x !== q)].slice(0, HISTORY_MAX);
    setStorage(HISTORY_KEY, history);
    this.setData({ history });
  },

  clearHistory() {
    removeStorage(HISTORY_KEY);
    this.setData({ history: [] });
    wx.showToast({ title: '已清空历史', icon: 'none' });
  },

  tapHistory(e) {
    const { q } = e.currentTarget.dataset;
    this.setData({ q });
    this.doSearch(true);
  },

  switchTab(e) {
    const tab = e.currentTarget.dataset.tab;
    if (tab === this.data.activeTab) return;
    const t = TABS.find(t => t.key === tab);
    this.setData({ activeTab: tab, isCode: t.isCode, page: 1, pages: 1, items: [] });
    if (this.data.q.trim()) this.doSearch(true);
  },

  onInput(e) {
    this.setData({ q: e.detail.value });
  },

  onClear() {
    this.setData({ q: '', items: [], total: 0 });
  },

  onSubmit() {
    const q = (this.data.q || '').trim();
    if (!q) return;
    if (q.length >= 2) this.saveHistory(q);
    this.doSearch(true);
  },

  onCancelSearch() {
    this.setData({ q: '', items: [], total: 0 });
  },

  async doSearch(reset) {
    if (reset) this.setData({ loading: true, page: 1, items: [] });
    else this.setData({ loading: true });
    const tab = TABS.find(t => t.key === this.data.activeTab);
    try {
      let data;
      if (tab.isCode) {
        // 代码表搜索：返回单页大结果
        data = await request({ url: tab.endpoint, data: { q: this.data.q }, silent: true });
        // /api/nhsa/.../search 返回 { count, q, results }; 老接口/兼容返回可能为 items/rows
        const items = (data && data.results) || (data && data.items) || (data && data.rows) || [];
        const total = (data && (data.count || data.total)) || items.length;
        this.setData({ items, total, loading: false, pages: 1 });
        this.logQuery(items.length);
      } else {
        // KP 主搜索
        const page = this.data.page;
        data = await request({ url: tab.endpoint, data: { q: this.data.q, page }, silent: true });
        const items = data.items || [];
        this.setData({
          items: this.data.items.concat(items),
          total: data.total || 0,
          pages: data.pages || 1,
          loading: false,
        });
        if (reset) this.logQuery(data.total || items.length);
      }
    } catch (e) {
      this.setData({ loading: false });
    }
  },

  logQuery(hitCount) {
    // 记录到 query_logs，供「热门搜索」用
    if (!this.data.q) return;
    request({
      url: '/api/query-log',
      method: 'POST',
      data: {
        openid: (getApp().globalData.openid || ''),
        q: this.data.q,
        cat: this.data.activeTab,
        hit_count: hitCount || 0,
      },
      silent: true,
    }).catch(() => {});
  },

  onReachBottom() {
    if (this.data.isCode) return;
    if (this.data.page >= this.data.pages) return;
    if (this.data.loading) return;
    this.setData({ page: this.data.page + 1 });
    this.doSearch(false);
  },

  onTapItem(e) {
    const { id } = e.currentTarget.dataset;
    if (!id) return;
    wx.navigateTo({ url: `/pages/kp-detail/kp-detail?id=${id}` });
  },

  onShareAppMessage() {
    const { q, activeTab } = this.data;
    return {
      title: q ? `医保智审 · 搜索 “${q}”` : '医保智审规则库',
      path: q ? `/pages/search/search?q=${encodeURIComponent(q)}&tab=${activeTab}` : '/pages/search/search',
    };
  },

  onShareTimeline() {
    const { q } = this.data;
    return {
      title: q ? `医保智审 · 搜索 “${q}”` : '医保智审规则库',
      query: q ? `q=${encodeURIComponent(q)}` : '',
    };
  },
});
