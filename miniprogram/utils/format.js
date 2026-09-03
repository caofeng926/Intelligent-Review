/**
 * 数据格式化工具
 */

/**
 * 安全地截断字符串
 */
function truncate(str, n = 80, suffix = '…') {
  if (str == null) return '';
  const s = String(str);
  if (s.length <= n) return s;
  return s.slice(0, n - 1).trim() + suffix;
}

/**
 * 格式化数字：12345 -> "12,345"
 */
function formatNumber(n) {
  if (n == null || isNaN(n)) return '—';
  return Number(n).toLocaleString('zh-CN');
}

/**
 * 把 ISO 日期 / "2025-12-15" / Date 转成可读短格式
 */
function formatDate(input, fmt = 'YYYY-MM-DD') {
  if (!input) return '—';
  let d = input;
  if (typeof input === 'string' || typeof input === 'number') {
    d = new Date(input);
  }
  if (!(d instanceof Date) || isNaN(d.getTime())) return String(input);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return fmt
    .replace('YYYY', y)
    .replace('MM', m)
    .replace('DD', dd);
}

/**
 * 相对时间："3 天前"
 */
function relativeTime(input) {
  if (!input) return '—';
  const t = new Date(input).getTime();
  if (isNaN(t)) return String(input);
  const diff = Date.now() - t;
  const sec = Math.floor(diff / 1000);
  if (sec < 60) return '刚刚';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} 天前`;
  const mo = Math.floor(day / 30);
  if (mo < 12) return `${mo} 个月前`;
  return `${Math.floor(mo / 12)} 年前`;
}

/**
 * 来源 label 转换
 */
const SOURCE_LABEL = {
  nhsa_batch: '医保局',
  pdf_2025:    '地方 PDF',
  nhsa:        '医保目录',
  kp:          '审核规则',
  yp_2025:     '2025 药品',
  yp_sx_2025:  '陕西 2025',
};

function sourceLabel(s) {
  return SOURCE_LABEL[s] || s || '其他';
}

/**
 * 高亮匹配的关键词（仅返回 array，view 层用 rich-text 渲染）
 */
function highlight(text, q) {
  if (!text || !q) return text;
  const re = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
  const parts = String(text).split(re);
  if (parts.length === 1) return text;
  // 输出 [{text:'前'}, {text:'X', highlight:true}, {text:'后'}, ...]
  return parts.reduce((acc, p, i) => {
    acc.push({ text: p });
    if (i < parts.length - 1) acc.push({ text: q, highlight: true });
    return acc;
  }, []);
}

module.exports = {
  truncate,
  formatNumber,
  formatDate,
  relativeTime,
  sourceLabel,
  highlight,
};
