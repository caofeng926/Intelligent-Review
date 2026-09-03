/**
 * 简单埋点
 * 第一版：console.log + wx.reportEvent (基础库 >= 2.7.0)
 * 后续可对接腾讯分析、自建埋点收集服务
 */

/**
 * 上报事件
 * event: 事件名
 * params: 附加参数 (string-only)
 */
// __DEV__ 由微信开发者工具在编译期注入 (--develop / npm script); 真机/生产环境未注入,
// 因此不要直接引用 __DEV__,改用 typeof 兜底,避免 ReferenceError。
const __IS_DEV__ = typeof __DEV__ !== 'undefined' && __DEV__ === true;

function track(event, params = {}) {
  // 1. console（开发期保留）
  if (__IS_DEV__) console.log('[track]', event, params);

  // 2. wx.reportEvent (低基础库会 warn 而非崩溃)
  if (typeof wx.reportEvent === 'function') {
    try {
      wx.reportEvent(event, params);
    } catch (e) {
      // 忽略
    }
  }

  // 3. 自定义埋点：写入本地队列，有网时上报
  const queue = wx.getStorageSync('yibao:track_queue') || [];
  queue.push({ event, params, t: Date.now() });
  // 只保留最近 100 条，避免无限增长
  if (queue.length > 100) queue.splice(0, queue.length - 100);
  try {
    wx.setStorageSync('yibao:track_queue', queue);
  } catch (e) {
    // storage 满了，忽略
  }
}

/**
 * 页面 PV（手动调用，配合 Page.onShow）
 */
function pageView(path) {
  track('page_view', { path });
}

module.exports = { track, pageView };
