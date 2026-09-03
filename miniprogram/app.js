/**
 * 医保智审 - App 入口
 * 负责全局生命周期、globalData、初始化用户体系
 */
const { request } = require('./utils/request');
const { getStorage, setStorage } = require('./utils/storage');
const { silentLogin } = require('./utils/auth.js');
const { track } = require('./utils/analytics.js');
const env = require('./utils/config').env;

App({
  globalData: {
    env,
    userInfo: null,
    openid: null,
    token: null,
    systemInfo: null,
    statsCache: null,        // 首页统计缓存（5 分钟）
    statsCacheAt: 0,
    loggedIn: false,
  },

  onLaunch(options) {
    // 0. 记录启动来源
    track('app_launch', { scene: String(options.scene || ''), path: options.path || '' });
    // 1. 记录启动信息
    const launchInfo = {
      scene: options.scene,
      path: options.path,
      query: options.query,
      launchedAt: Date.now(),
    };
    console.log('[App] onLaunch', launchInfo);

    // 2. 读取 systemInfo（屏幕、导航、安全区）
    try {
      const sys = wx.getSystemInfoSync();
      const menuInfo = wx.getDeviceInfo ? wx.getDeviceInfo() : null;
      this.globalData.systemInfo = {
        ...sys,
        ...menuInfo,
        // 自定义导航栏时需要的 statusBarHeight
        statusBarHeight: sys.statusBarHeight || 20,
        // 安全区底部
        safeBottom: (sys.screenHeight || 0) - (sys.safeArea?.bottom || 0),
      };
    } catch (e) {
      console.warn('[App] getSystemInfoSync 失败', e);
    }

    // 3. 恢复登录态（如果之前登录过）
    const savedToken = getStorage('access_token');
    const savedOpenid = getStorage('openid');
    if (savedToken) this.globalData.token = savedToken;
    if (savedOpenid) this.globalData.openid = savedOpenid;

    // 4. 隐私协议（基础库 >= 3.0.1 强制要求）
    //    4.1 检查是否需要展示 privacy 弹窗
    if (wx.getPrivacySetting) {
      wx.getPrivacySetting({
        success: (res) => {
          if (res.needAuthorization) {
            // 用户尚未同意隐私协议，把 flag 存到 globalData，
            // pages/privacy 页面会读取并展示
            this.globalData.privacyNeedAuth = true;
          } else {
            this.globalData.privacyNeedAuth = false;
          }
        },
        fail: () => {
          this.globalData.privacyNeedAuth = false;
        },
      });
    }

    // 5. 监听网络状态变化（弱网降级）
    if (wx.onNetworkStatusChange) {
      wx.onNetworkStatusChange((res) => {
        this.globalData.networkOnline = res.isConnected;
        if (!res.isConnected) {
          wx.showToast({
            title: '当前网络不可用',
            icon: 'none',
            duration: 2000,
          });
        }
      });
    }
    if (wx.getNetworkType) {
      wx.getNetworkType({
        success: (res) => { this.globalData.networkType = res.networkType; },
      });
    }

    // 6. 静默预热首页数据（让 tabs 切换更快）
    this.prewarmHome();

    // 7. 静默登录（拿 openid + token，失败不影响首屏）
    silentLogin(this).then((data) => {
      this.globalData.loggedIn = !!(data && data.token);
    }).catch(() => {
      this.globalData.loggedIn = false;
    });
  },

  onShow(options) {
    // 小程序从后台切到前台
    this.globalData.foregroundAt = Date.now();
  },

  onHide() {
    // 用户离开小程序，写入埋点
    const elapsed = Date.now() - (this.globalData.foregroundAt || Date.now());
    console.log('[App] onHide elapsed(ms)=', elapsed);
  },

  onError(err) {
    console.error('[App] onError', err);
    // 可对接 wx.reportMonitor / 自定义打点
  },

  /**
   * 预热首页统计 (写入缓存)
   * 让切换到首页 tab 时首屏 < 1.5s
   */
  prewarmHome() {
    request({ url: '/api/stats', method: 'GET' })
      .then((data) => {
        this.globalData.statsCache = data;
        this.globalData.statsCacheAt = Date.now();
      })
      .catch(() => { /* 忽略错误，下一次切回首页再拉 */ });
  },

  /**
   * 全局 toast — 复用弹层
   */
  toast(title, icon = 'none', duration = 1800) {
    wx.showToast({ title, icon, duration, mask: false });
  },
});
