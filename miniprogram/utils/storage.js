/**
 * 本地存储封装
 * - key 加前缀，避免与其它模块冲突
 * - 自动 JSON 序列化
 * - 静默失败（无 toast）
 */
const PREFIX = 'yibao:';   // 全局前缀

function makeKey(k) {
  return PREFIX + k;
}

function setStorage(key, value) {
  try {
    wx.setStorageSync(makeKey(key), value);
    return true;
  } catch (e) {
    console.warn('[storage] set failed', key, e);
    return false;
  }
}

function getStorage(key, defaultValue = null) {
  try {
    const v = wx.getStorageSync(makeKey(key));
    if (v === '' || v === null || v === undefined) return defaultValue;
    return v;
  } catch (e) {
    console.warn('[storage] get failed', key, e);
    return defaultValue;
  }
}

function removeStorage(key) {
  try {
    wx.removeStorageSync(makeKey(key));
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * 带时效的缓存
 * ttl: 毫秒
 */
function setCache(key, value, ttl) {
  const wrapped = {
    v: value,
    e: Date.now() + ttl,
  };
  return setStorage(key, wrapped);
}

function getCache(key, defaultValue = null) {
  const wrapped = getStorage(key, null);
  if (!wrapped || typeof wrapped !== 'object' || wrapped.e == null) return defaultValue;
  if (Date.now() > wrapped.e) {
    removeStorage(key);
    return defaultValue;
  }
  return wrapped.v;
}

module.exports = {
  setStorage,
  getStorage,
  removeStorage,
  setCache,
  getCache,
};
