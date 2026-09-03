Component({
  properties: {
    type: { type: String, value: 'spinner' }, // spinner | skeleton
    tip: { type: String, value: '加载中…' },
    rows: { type: Number, value: 3 },
  },
});
