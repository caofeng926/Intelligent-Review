Page({
  data: {
    agreed: false,
    privacyContractLoaded: false,
  },

  onLoad() {
    if (wx.getPrivacySetting) {
      wx.getPrivacySetting({
        success: (res) => {
          this.setData({ agreed: !res.needAuthorization });
        },
      });
    }
  },

  /**
   * 新版隐私授权：button open-type="agreePrivacyAuthorization" 触发
   * 接收 detail = { event, agree } 两种可能
   */
  handleAgree(e) {
    const detail = (e && e.detail) || {};
    // event === 'agree'  同意; 'disagree' 拒绝
    if (detail.event === 'disagree') {
      wx.showToast({ title: '需同意后才能继续', icon: 'none' });
      return;
    }
    if (wx.onNeedPrivacyAuthorization) {
      wx.onNeedPrivacyAuthorization();
    }
    this.setData({ agreed: true });
    wx.showToast({ title: '感谢您的信任', icon: 'success' });
    setTimeout(() => wx.navigateBack(), 800);
  },

  openPrivacyContract() {
    if (wx.openPrivacyContract) {
      wx.openPrivacyContract({ success: () => {} });
    } else {
      wx.showToast({ title: '当前微信版本不支持，请升级到最新版本', icon: 'none' });
    }
  },
});
