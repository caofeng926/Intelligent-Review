const { request } = require('../../utils/request');
const { formatDate, sourceLabel } = require('../../utils/format');
const { getStorage } = require('../../utils/storage');
const svgs = require('../../utils/svgs.js');
const app = getApp();

Page({
  data: {
    id: null,
    detail: null,
    codes: [],
    manufacturers: [],
    loading: true,
    empty: false,
    shareIcon: svgs.share || '',
    starIcon: svgs.star || '',
    starFilledIcon: svgs.star_filled || '',
    isFav: false,
    openid: '',
  },

  onLoad(options) {
    const id = options.id;
    if (!id) {
      this.setData({ loading: false, empty: true });
      return;
    }
    this.setData({
      id,
      openid: (app.globalData.openid || getStorage('openid') || ''),
    });
    this.loadDetail(id);
  },

  onShow() {
    // 重新打开详情页时刷新收藏状态（用户可能从「我的」跳回来）
    if (this.data.id && this.data.openid) this.checkFav(this.data.id);
  },

  async loadDetail(id) {
    this.setData({ loading: true });
    try {
      const data = await request({ url: `/api/kp/${id}`, silent: true });
      const detail = {
        id: data.id || id,
        name: data.subject_name || data.name || data.subject || '—',
        rule_subject: data.rule_subject || '',
        source: data.source || '',
        source_label: sourceLabel(data.source),
        batch_label: data.batch_label || '',
        pub_date: data.pub_date || '',
        code_count: data.code_count || 0,
        rule_id: data.rule_id,
        codes: data.codes || [],
        related: data.related || [],
      };
      this.setData({ detail, loading: false, empty: false });
      wx.setNavigationBarTitle({ title: (detail.name || '').slice(0, 14) });
      // 异步查是否已收藏
      if (this.data.openid) this.checkFav(id);
    } catch (e) {
      this.setData({ loading: false, empty: true });
    }
  },

  async checkFav(kpId) {
    try {
      const data = await request({
        url: '/api/fav/check',
        data: { openid: this.data.openid, ids: kpId },
        silent: true,
      });
      this.setData({ isFav: (data.favs || []).includes(Number(kpId)) });
    } catch (e) { /* 静默失败 */ }
  },

  async onToggleFav() {
    const openid = this.data.openid;
    if (!openid) {
      wx.showToast({ title: '登录中，请稍后再试', icon: 'none' });
      return;
    }
    const id = this.data.id;
    const wasFav = this.data.isFav;
    // 乐观更新
    this.setData({ isFav: !wasFav });
    try {
      if (wasFav) {
        await request({
          url: '/api/fav',
          method: 'DELETE',
          data: { openid, kp_id: Number(id) },
          silent: true,
        });
        wx.showToast({ title: '已取消收藏', icon: 'none' });
      } else {
        await request({
          url: '/api/fav',
          method: 'POST',
          data: {
            openid,
            kp_id: Number(id),
            kp_name: (this.data.detail && this.data.detail.name) || '',
            batch_label: (this.data.detail && this.data.detail.batch_label) || '',
          },
          silent: true,
        });
        wx.showToast({ title: '已加入收藏', icon: 'success' });
      }
    } catch (e) {
      // 回滚
      this.setData({ isFav: wasFav });
      wx.showToast({ title: '操作失败，请稍后重试', icon: 'none' });
    }
  },

  onSubscribe() {
    // 订阅消息 — 用户授权后服务端可下发「医保局新政策」通知
    // 注意：订阅消息模板 ID 必须去 mp.weixin.qq.com 后台「订阅消息 → 公共模板库」申请
    // TODO: 提交审核前替换为公众平台「订阅消息 → 公共模板库」申请到的真实模板 ID
    // 例如 const tmplIds = ['aBcD1EfGhI2JkLmN3OpQ4rStUvWxYz5A'];  (32 字符)
    const tmplIds = ['TODO_TEMPLATE_ID_HERE'];
    if (typeof wx.requestSubscribeMessage !== 'function') {
      wx.showToast({ title: '当前微信版本不支持', icon: 'none' });
      return;
    }
    wx.requestSubscribeMessage({
      tmplIds,
      success: (res) => {
        const accepted = res[tmplIds[0]] === 'accept';
        if (accepted && this.data.openid) {
          request({
            url: '/api/subscribe',
            method: 'POST',
            data: {
              openid: this.data.openid,
              tmpl_id: tmplIds[0],
              rule_subject: (this.data.detail && this.data.detail.rule_subject) || '',
            },
            silent: true,
          }).catch(() => {});
          wx.showToast({ title: '订阅成功', icon: 'success' });
        } else {
          wx.showToast({ title: '已取消订阅', icon: 'none' });
        }
      },
      fail: () => {
        wx.showToast({ title: '订阅失败', icon: 'none' });
      },
    });
  },

  onCodeTap(e) {
    const { code } = e.currentTarget.dataset;
    if (!code) return;
    wx.navigateTo({ url: `/pages/code-lookup/code-lookup?code=${encodeURIComponent(code)}` });
  },

  onShareAppMessage() {
    const { detail, id } = this.data;
    return {
      title: detail?.name || '医保智审 · 知识点详情',
      path: `/pages/kp-detail/kp-detail?id=${id}`,
    };
  },

  onShareTimeline() {
    const { detail, id } = this.data;
    return {
      title: detail?.name || '医保智审',
      query: `id=${id}`,
    };
  },
});
