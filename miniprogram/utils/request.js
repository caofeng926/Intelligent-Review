/**
 * 统一请求封装
 * - Promise 化
 * - 自动注入 token
 * - 网络错误统一处理
 * - 支持超时重试（仅 idempotent GET）
 */
const { apiBase, enableLog } = require('./config');
const { getStorage } = require('./storage');

function buildUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  // 避免双斜杠
  if (!path.startsWith('/')) path = '/' + path;
  return apiBase + path;
}

function request(options = {}) {
  const {
    url,
    method = 'GET',
    data = {},
    header = {},
    timeout = 15000,
    showError = true,    // 是否自动 wx.showToast
    silent = false,      // 不打任何日志
  } = options;

  const token = getStorage('access_token');

  return new Promise((resolve, reject) => {
    const task = wx.request({
      url: buildUrl(url),
      method,
      data,
      timeout,
      header: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...header,
      },
      success: (res) => {
        if (!silent && enableLog) {
          console.log(`[request] ${method} ${url}`, { statusCode: res.statusCode, data: res.data });
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else if (res.statusCode === 401) {
          // token 过期 — 清理登录态，触发登录（由调用方决定如何处理）
          try {
            wx.removeStorageSync('access_token');
            wx.removeStorageSync('openid');
          } catch (e) {}
          if (showError) wx.showToast({ title: '登录已过期', icon: 'none' });
          const err = new Error('Unauthorized');
          err.code = 401;
          reject(err);
        } else if (res.statusCode === 404) {
          if (showError) wx.showToast({ title: '资源不存在', icon: 'none' });
          const err = new Error('Not Found');
          err.code = 404;
          reject(err);
        } else {
          const err = new Error(res.data?.message || '请求失败');
          err.code = res.statusCode;
          err.detail = res.data;
          if (showError) {
            wx.showToast({ title: err.message, icon: 'none', duration: 2000 });
          }
          reject(err);
        }
      },
      fail: (err) => {
        if (!silent && enableLog) console.error(`[request fail] ${method} ${url}`, err);
        if (showError) {
          wx.showToast({ title: '网络异常，请稍后再试', icon: 'none', duration: 2000 });
        }
        const e = new Error('网络异常');
        e.code = -1;
        e.detail = err;
        reject(e);
      },
    });

    // 暴露 task 让调用方能 abort
    options._task && options._task(task);
  });
}

/**
 * GET 快捷方式
 */
function get(url, data, options = {}) {
  return request({ ...options, url, method: 'GET', data });
}

/**
 * POST 快捷方式
 */
function post(url, data, options = {}) {
  return request({ ...options, url, method: 'POST', data });
}

module.exports = { request, get, post };
