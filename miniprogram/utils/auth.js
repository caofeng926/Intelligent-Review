/**
 * 微信登录管理
 * 微信小程序免强制登录，按需调用。
 * 第一版不会强制弹窗，登录态为可选。后续接入订阅消息、个人中心时再扩展。
 */
const { getStorage, setStorage, removeStorage } = require('./storage');

/**
 * 静默登录：拿 code 换 openid，不弹授权窗口。
 * 调用方只需 await，无需任何用户交互。
 */
async function silentLogin(app) {
  // 已登录则直接返回
  let token = getStorage('access_token');
  let openid = getStorage('openid');
  if (token && openid) {
    app.globalData.token = token;
    app.globalData.openid = openid;
    return { token, openid };
  }

  // wx.login() 拿 code
  const code = await new Promise((resolve, reject) => {
    wx.login({
      success: (r) => (r.code ? resolve(r.code) : reject(new Error('wx.login no code'))),
      fail: reject,
    });
  });

  // 把 code 发到后端换 openid / token
  // 后端要实现：POST /api/auth/wechat-login { code } -> { openid, access_token }
  try {
    const { request } = require('./request');
    const data = await request({
      url: '/api/auth/wechat-login',
      method: 'POST',
      data: { code },
      silent: true,
      showError: false,
    });
    if (data && data.access_token && data.openid) {
      setStorage('access_token', data.access_token);
      setStorage('openid', data.openid);
      app.globalData.token = data.access_token;
      app.globalData.openid = data.openid;
      return { token: data.access_token, openid: data.openid };
    }
  } catch (e) {
    console.warn('[auth] 后端 /api/auth/wechat-login 不可用（开发期可忽略）', e.message);
  }
  return { token: null, openid: null };
}

/**
 * 主动登出：清空登录态
 */
function logout(app) {
  removeStorage('access_token');
  removeStorage('openid');
  app.globalData.token = null;
  app.globalData.openid = null;
}

module.exports = { silentLogin, logout };
