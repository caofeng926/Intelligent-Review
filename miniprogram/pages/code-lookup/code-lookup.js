const { request } = require('../../utils/request');
const svgs = require('../../utils/svgs.js');

Page({
  data: {
    code: '',
    result: null,
    notFound: false,
    loading: false,
    searchIcon: svgs.search || '',
    scanIcon: svgs.scan || '',
  },

  onLoad(options) {
    if (options.code) {
      this.setData({ code: decodeURIComponent(options.code) });
      this.doLookup();
    }
  },

  onInput(e) {
    this.setData({ code: (e.detail.value || '').toUpperCase().trim() });
  },

  onSubmit() {
    if (!this.data.code) return;
    this.doLookup();
  },

  onScan() {
    if (!wx.scanCode) {
      return wx.showToast({ title: '当前微信版本不支持扫码', icon: 'none' });
    }
    // 仅允许小程序 tap 触发 scanCode
    wx.scanCode({
      onlyFromCamera: false,
      scanType: ['qrCode', 'barCode'],
      success: (res) => {
        // 扫到的可能是 URL，也可能直接是 19 位编码
        let raw = res.result || '';
        const m = raw.match(/[A-Z0-9]{15,20}/i);
        if (m) raw = m[0];
        this.setData({ code: raw.toUpperCase() });
        if (raw.length >= 8) this.doLookup();
      },
      fail: () => {},
    });
  },

  async doLookup() {
    const code = this.data.code;
    if (!code) return;
    this.setData({ loading: true, result: null, notFound: false });
    try {
      const data = await request({ url: `/api/code/${encodeURIComponent(code)}`, silent: true });
      const items = data.items || [];
      if (data.kind === 'rule_code' && !items.length) {
        this.setData({ loading: false, notFound: true });
        return;
      }
      this.setData({ loading: false, result: data, notFound: false });
    } catch (e) {
      this.setData({ loading: false, notFound: true });
    }
  },

  onTapItem(e) {
    const { id } = e.currentTarget.dataset;
    if (!id) return;
    wx.navigateTo({ url: `/pages/kp-detail/kp-detail?id=${id}` });
  },

  onShareAppMessage() {
    const { code } = this.data;
    return code
      ? { title: `医保智审 · 编码 ${code}`, path: `/pages/code-lookup/code-lookup?code=${encodeURIComponent(code)}` }
      : { title: '医保智审 · 编码反查', path: '/pages/code-lookup/code-lookup' };
  },
});
