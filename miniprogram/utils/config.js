/**
 * 全局配置
 * API 基地址根据 env 切换。开发时勾"不校验合法域名"，
 * 生产环境必须使用 HTTPS 域名且在后台登记。
 */
const ENV = 'prod'; // dev | staging | prod

const config = {
  dev: {
    apiBase: 'https://api.yibao-zs.cn', // 开发时也指向生产域名，避免 baseURL 不一致
    enableLog: true,
  },
  staging: {
    apiBase: 'https://api.yibao-zs.cn',
    enableLog: true,
  },
  prod: {
    apiBase: 'https://api.yibao-zs.cn',
    enableLog: false,
  },
};

module.exports = {
  env: ENV,
  ...config[ENV],
};

/**
 * 外部覆盖：如果你想单独请求某个全路径的 URL，可以直接用 wx.request
 * 但 99% 场景应该用 utils/request.js
 */
