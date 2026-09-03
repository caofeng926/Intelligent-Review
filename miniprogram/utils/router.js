/**
 * 路由工具
 * - nav / back / tab / reLaunch / relaunch
 * - 自动选择 navigateTo 还是 redirectTo（如果当前栈 > 9）
 */

/**
 * 普通跳转（保留当前页）
 */
function nav(path, params) {
  const url = params ? buildUrl(path, params) : path;
  return new Promise((resolve, reject) => {
    wx.navigateTo({
      url,
      success: resolve,
      fail: reject,
    });
  });
}

/**
 * 关闭当前页跳转（不保留）
 */
function redirect(path, params) {
  const url = params ? buildUrl(path, params) : path;
  return new Promise((resolve, reject) => {
    wx.redirectTo({ url, success: resolve, fail: reject });
  });
}

/**
 * 切换 tabBar 页面
 */
function tab(path) {
  return new Promise((resolve, reject) => {
    wx.switchTab({ url: path, success: resolve, fail: reject });
  });
}

/**
 * 重启到指定页面（关闭所有页 → 重新加载）
 */
function reLaunch(path, params) {
  const url = params ? buildUrl(path, params) : path;
  return new Promise((resolve, reject) => {
    wx.reLaunch({ url, success: resolve, fail: reject });
  });
}

/**
 * 后退一页
 */
function back(delta = 1) {
  return new Promise((resolve) => {
    wx.navigateBack({ delta, success: resolve, fail: () => resolve(false) });
  });
}

/**
 * 回首页（关闭所有页）
 */
function home() {
  return reLaunch('/pages/index/index');
}

/**
 * 构建带 query 的 URL
 */
function buildUrl(path, params) {
  if (!params) return path;
  const query = Object.keys(params)
    .filter((k) => params[k] !== undefined && params[k] !== null)
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
    .join('&');
  return query ? `${path}?${query}` : path;
}

module.exports = { nav, redirect, tab, reLaunch, back, home, buildUrl };
