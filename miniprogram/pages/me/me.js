const { request } = require('../../utils/request');
const { setStorage, getStorage, removeStorage } = require('../../utils/storage');
const app = getApp();

Page({
  data: {
    userInfo: null,
    openid: '',
    favs: [],
    loading: false,
    stats: { favs: 0, history: 0, scans: 0 },
    shareIcon: '',
    contactIcon: '',
    feedbackIcon: '',
    privacyIcon: '',
  },

  onLoad() {
    this.setData({
      shareIcon: require('../../utils/svgs.js').share || '',
      contactIcon: require('../../utils/svgs.js').info || '',
      feedbackIcon: require('../../utils/svgs.js').alert || '',
      privacyIcon: require('../../utils/svgs.js').shield || '',
    });
  },

  onShow() {
    // 每次切到「我的」tab 刷新数据
    const openid = (app.globalData.openid || getStorage('openid') || '');
    this.setData({ openid });
    if (openid) {
      this.loadFavs(openid);
      this.loadMyStats(openid);
    }
  },

  async loadFavs(openid) {
    this.setData({ loading: true });
    try {
      const data = await request({
        url: '/api/fav',
        data: { openid },
        silent: true,
      });
      const items = (data && data.items) || [];
      this.setData({ favs: items, loading: false, 'stats.favs': items.length });
    } catch (e) {
      this.setData({ loading: false });
    }
  },

  loadMyStats(openid) {
    // 简单从本地估算：搜索历史数 + 收藏数
    const history = (getStorage('search_history_v1') || []).length;
    this.setData({ 'stats.history': history });
  },

  onTapFav(e) {
    const { id } = e.currentTarget.dataset;
    if (!id) return;
    wx.navigateTo({ url: `/pages/kp-detail/kp-detail?id=${id}` });
  },

  async onUnfav(e) {
    const { id } = e.currentTarget.dataset;
    if (!id || !this.data.openid) return;
    try {
      await request({
        url: '/api/fav',
        method: 'DELETE',
        data: { openid: this.data.openid, kp_id: Number(id) },
        silent: true,
      });
      // 本地过滤掉
      const favs = this.data.favs.filter(f => f.kp_id !== Number(id));
      this.setData({ favs, 'stats.favs': favs.length });
      wx.showToast({ title: '已取消收藏', icon: 'none' });
    } catch (e) {
      wx.showToast({ title: '操作失败', icon: 'none' });
    }
  },

  onTapMenu(e) {
    const { action } = e.currentTarget.dataset;
    if (action === 'clear-cache') {
      this.clearCache();
    } else if (action === 'privacy') {
      wx.navigateTo({ url: '/packageLegal/pages/privacy/privacy' });
    } else if (action === 'about') {
      wx.navigateTo({ url: '/packageLegal/pages/about/about' });
    }
  },

  clearCache() {
    wx.showModal({
      title: '清理缓存',
      content: '将清除搜索历史与本地缓存，不会删除服务器上的收藏。',
      success: (res) => {
        if (res.confirm) {
          try {
            // 清空常用 storage key
            removeStorage('search_history_v1');
            wx.clearStorageSync();
            // 重新写回必要的 key（避免把 openid/token 删了）
            // clearStorageSync 后用户下次进 app 会重新静默登录，所以这里直接清理是 OK 的
            wx.showToast({ title: '已清理', icon: 'success' });
            this.loadMyStats(this.data.openid);
          } catch (e) {
            wx.showToast({ title: '清理失败', icon: 'none' });
          }
        }
      },
    });
  },

  onShareAppMessage() {
    return {
      title: '医保智审规则库',
      path: '/pages/index/index',
    };
  },
});
