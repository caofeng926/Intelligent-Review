const svgs = require('../../utils/svgs.js');

Component({
  properties: {
    icon: { type: String, value: 'search' },
    title: { type: String, value: '暂无内容' },
    desc:  { type: String, value: '' },
    actionText: { type: String, value: '' },
  },
  data: {
    iconSvg: '',
  },
  observers: {
    'icon': function (icon) {
      const raw = svgs[icon] || svgs.search || '';
      // 给 svg 加 class 方便 CSS 上色
      const html = raw.replace('<svg ', '<svg class="empty-svg-color" ');
      this.setData({ iconSvg: html });
    },
  },
  lifetimes: {
    attached() {
      const raw = svgs[this.data.icon] || svgs.search || '';
      this.setData({ iconSvg: raw.replace('<svg ', '<svg class="empty-svg-color" ') });
    },
  },
  methods: {
    onAction() { this.triggerEvent('action'); },
  },
});
