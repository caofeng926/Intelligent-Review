Component({
  options: {
    multipleSlots: true,
    styleIsolation: 'apply-shared',
  },

  properties: {
    // 主数据
    item: {
      type: Object,
      value: {},
    },
    // 紧凑模式（搜索结果列表）
    compact: {
      type: Boolean,
      value: false,
    },
    // 关键词（高亮用）
    keyword: {
      type: String,
      value: '',
    },
  },

  data: {
    // 内部 computed
    cat: '',
    catLabel: '',
    catClass: '',
    titleParts: [],
    desc: '',
    codeCount: 0,
  },

  observers: {
    'item, keyword': function (item, keyword) {
      if (!item) return;
      // 1. 分类色
      const cat = item.cat || item.category || inferCat(item);
      const catClass = catClassOf(cat);
      this.setData({
        cat,
        catLabel: catLabelOf(cat),
        catClass,
        titleParts: splitHighlight(item.subject_name || item.name || '未命名', keyword),
        desc: truncate(item.rule_subject || item.subject || '', 60),
        codeCount: item.code_count || item.codes?.length || 0,
      });
    },
  },

  methods: {
    onTap() {
      this.triggerEvent('tap', { item: this.data.item });
    },
  },
});

// ------------ helpers ------------
function inferCat(item) {
  if (item.cat_l1_name || item.cat_l2_name) return 'hc';
  if (item.diagnosis_name) return 'icd';
  if (item.catalog_full_name) return 'ivd';
  if (item.reg_name) return 'yp';
  if (item.class_name) return 'tcm';
  if (item.name && item.explain) return 'ms';
  return 'rule';
}
function catClassOf(cat) {
  return 'cat-' + cat;
}
function catLabelOf(cat) {
  return {
    hc: '耗材', ivd: '试剂', yp: '药品',
    icd: 'ICD', tcm: '中医', ms: '医疗服务', rule: '规则',
  }[cat] || '规则';
}
function truncate(s, n) {
  if (!s) return '';
  return String(s).length > n ? String(s).slice(0, n - 1) + '…' : s;
}
function splitHighlight(text, q) {
  if (!text) return [{ text: '' }];
  if (!q) return [{ text }];
  const re = new RegExp(escapeReg(q), 'gi');
  const parts = String(text).split(re);
  if (parts.length <= 1) return [{ text }];
  return parts.reduce((acc, p, i) => {
    acc.push({ text: p });
    if (i < parts.length - 1) acc.push({ text: q, highlight: true });
    return acc;
  }, []);
}
function escapeReg(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
