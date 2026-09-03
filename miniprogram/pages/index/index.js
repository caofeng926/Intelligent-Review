const { request } = require('../../utils/request');
const { formatNumber, relativeTime } = require('../../utils/format');
const svgs = require('../../utils/svgs.js');
const app = getApp();

const STAT_KEY = 'home_stats';
const STAT_TTL = 5 * 60 * 1000;

Page({
  data: {
    stats: {
      knowledge_points: 0,
      rules: 0,
      consumables: 0,
      yp_2025: 0,
      tcm: 0,
      icd: 0,
      ivd: 0,
      ms: 0,
    },
    recent: [],
    refreshing: false,
    updatedAt: '',
    loaded: false,
    searchIcon: svgs.search || '',
    grid: [
      { key: 'search',     name: '关键词搜索',  sub: '药品/规则',       url: '/pages/search/search',           color: 'primary' },
      { key: 'code',       name: '编码反查',    sub: '19 位代码',       url: '/pages/code-lookup/code-lookup', color: 'accent'  },
      { key: 'category',   name: '分类浏览',    sub: '七大目录',         url: '/pages/category/category',       color: 'hc'      },
      { key: 'favorites',  name: '我的收藏',    sub: '登录后可用',       url: '',                               color: 'rule', disabled: true },
    ],
  },

  onLoad() {},

  onShow() {
    // 优先用 app 预热缓存，避免空白闪烁
    const cached = app.globalData.statsCache;
    if (cached) {
      this.setData({ stats: cached, loaded: true });
      this.applyUpdatedAt(app.globalData.statsCacheAt);
    }
    this.loadStats({ useCache: true });
  },

  async loadStats({ useCache = true } = {}) {
    if (!useCache) this.setData({ refreshing: true });
    try {
      const [stats, recentRes] = await Promise.all([
        request({ url: '/api/stats', method: 'GET', silent: true }),
        request({ url: '/api/recent', method: 'GET', data: { limit: 8 }, silent: true }),
      ]);
      const formatted = { ...this.data.stats, ...formatStats(stats) };
      const items = (recentRes && recentRes.items) || [];
      this.setData({
        stats: formatted,
        recent: items,
        loaded: true,
        refreshing: false,
      });
      this.applyUpdatedAt(Date.now());
      app.globalData.statsCache = formatted;
      app.globalData.statsCacheAt = Date.now();
    } catch (e) {
      this.setData({ refreshing: false });
      // 网络失败保留旧数据 + 显示提示
      if (!this.data.loaded) {
        wx.showToast({ title: '网络异常', icon: 'none' });
      }
    }
  },

  applyUpdatedAt(t) {
    if (t) this.setData({ updatedAt: relativeTime(t) });
  },

  onPullDownRefresh() {
    this.loadStats({ useCache: false }).then(() => wx.stopPullDownRefresh());
  },

  onGridTap(e) {
    const { url, key, disabled } = e.currentTarget.dataset;
    if (disabled) {
      return wx.showToast({ title: '登录后开放', icon: 'none' });
    }
    if (!url) return;
    if (url.startsWith('/pages/search') || url.startsWith('/pages/code-lookup') || url.startsWith('/pages/category')) {
      wx.switchTab({ url });
    } else {
      wx.navigateTo({ url });
    }
    wx.reportEvent && wx.reportEvent('home_grid_tap', { key });
  },

  onTapRecent(e) {
    const { id } = e.currentTarget.dataset;
    if (!id) return;
    wx.navigateTo({ url: `/pages/kp-detail/kp-detail?id=${id}` });
  },

  onSearchInput(e) {
    const v = (e.detail.value || '').trim();
    this.setData({ searchInput: v });
  },

  onSearchConfirm(e) {
    const q = (e.detail.value || '').trim();
    if (!q) return;
    wx.switchTab({ url: `/pages/search/search?q=${encodeURIComponent(q)}` });
  },

  onShareAppMessage() {
    return {
      title: '医保智审规则库 · 让审核员随身检索',
      path: '/pages/index/index',
    };
  },

  onShareTimeline() {
    return {
      title: '医保审核员的检索工具 · 医保智审',
      query: '',
    };
  },
});

function formatStats(d) {
  return {
    knowledge_points: d.knowledge_points || 0,
    rules: d.rules || 0,
    consumables: d.consumables || 0,
    yp_2025: d.yp_2025 || 0,
    tcm: d.tcm || 0,
    icd: d.icd || 0,
    ivd: d.ivd || 0,
    ms: d.ms || 0,
  };
}
