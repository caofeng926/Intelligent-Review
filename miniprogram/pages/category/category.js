const { request } = require('../../utils/request');
const svgs = require('../../utils/svgs.js');

const CATS = [
  { key: 'kp',  name: '审核规则',    sub: 'NHSA + 各省 PDF', icon: 'rule',  cls: 'rule', count: 0 },
  { key: 'yp',  name: '医保药品',    sub: '2025 国家医保目录', icon: 'pill',  cls: 'yp',   count: 0 },
  { key: 'hc',  name: '医用耗材',    sub: '17 万 + 耗材条目',  icon: 'hc',    cls: 'hc',   count: 0 },
  { key: 'ivd', name: '诊断试剂',    sub: 'IVD 体外诊断',     icon: 'ivd',   cls: 'ivd',  count: 0 },
  { key: 'icd', name: 'ICD-10 疾病', sub: '国际疾病分类',     icon: 'icd',   cls: 'icd',  count: 0 },
  { key: 'tcm', name: '中医病证',    sub: '中医病症 / 证候',  icon: 'tcm',   cls: 'tcm',  count: 0 },
  { key: 'ms',  name: '医疗服务',    sub: '诊疗项目 / 价格',  icon: 'ms',    cls: 'ms',   count: 0 },
];

Page({
  data: {
    cats: CATS.map(c => ({ ...c, iconSvg: svgs[c.icon] || '' })),
  },

  onShow() {
    this.loadCounts();
  },

  async loadCounts() {
    try {
      const data = await request({ url: '/api/stats', silent: true });
      // 字段映射
      const mapping = {
        kp:  data.knowledge_points,
        yp:  data.yp_2025,
        hc:  data.consumables,
        ivd: data.ivd,
        icd: data.icd,
        tcm: data.tcm,
        ms:  data.ms,
      };
      const cats = this.data.cats.map(c => ({ ...c, count: mapping[c.key] || c.count }));
      this.setData({ cats });
    } catch (e) {
      // 网络异常保留原数据
    }
  },

  onTapCat(e) {
    const { key, cat } = e.currentTarget.dataset;
    if (!cat) return;
    if (key === 'kp') {
      wx.switchTab({ url: '/pages/search/search' });
      return;
    }
    // 其余切换到 search 时预填 tab 与关键词
    wx.navigateTo({ url: `/pages/search/search?tab=${key}` });
  },
});
