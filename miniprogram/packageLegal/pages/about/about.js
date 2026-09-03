Page({
  data: {
    version: '1.0.0',
    buildAt: '2026-07-14',
    // TODO: 提交审核前替换为工信部 ICP 备案号, 如 '京ICP备12345678号-1'
    icpFiling: '待补充',
  },

  copyOpenid() {
    wx.setClipboardData({
      data: 'yibao-zs',
      success: () => wx.showToast({ title: '客服微信已复制' }),
    });
  },

  goPrivacy() {
    wx.navigateTo({ url: '/packageLegal/pages/privacy/privacy' });
  },
});
