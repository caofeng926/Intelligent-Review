# 医保智审规则库 · 微信小程序

把现有的 Flask + SQLite 医保审核规则库搬到微信生态。
原生 WXML/WXSS/WXS，启用 Skyline 渲染引擎。

---

## 🗂 目录结构

```
miniprogram/
├── app.js                  # App 生命周期 + globalData
├── app.json                # 全局配置（pages, tabBar, window）
├── app.wxss                # 全局样式 — Clinical Clarity v2
├── project.config.json     # 微信开发者工具配置（AppID, libVersion）
├── sitemap.json            # 微信搜索索引
├── utils/
│   ├── config.js           # API 基地址 + 环境切换
│   ├── request.js          # Promise 化的 wx.request
│   ├── storage.js          # wx.setStorageSync 封装（含 TTL）
│   ├── format.js           # truncate/number/date/highlight
│   ├── svgs.js             # 内联 SVG 图标库
│   ├── auth.js             # 微信登录（wx.login → openid）
│   ├── router.js           # navigateTo / switchTab 封装
│   └── analytics.js        # 简单埋点
├── components/
│   ├── kp-card/            # 知识点列表卡片（搜索结果复用）
│   ├── empty-state/        # 空状态
│   └── loading/            # 加载/骨架屏
├── pages/
│   ├── index/              # 首页（数据卡 + 入口宫格 + 七大代码表入口）
│   ├── search/             # 搜索（7 个 tab 切换 + 滚动加载）
│   ├── code-lookup/        # 编码反查（输入 + 扫码）
│   ├── category/           # 分类浏览（七大代码表分页）
│   ├── kp-detail/          # 知识点详情
│   ├── privacy/            # 隐私协议
│   └── about/              # 关于 + 客服
└── README.md
```

---

## 🚀 第一次跑起来

### 1. 申请 AppID
- 注册：https://mp.weixin.qq.com/
- 个人主体（限制较多）/ 企业主体（推荐，可选「医疗-医疗信息查询」类目）
- 拿到 AppID 后，编辑 `project.config.json` 的 `appid` 字段，从 `touristappid` 改成你的真实 AppID

### 2. 导入开发者工具
- 下载：https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html
- 打开开发者工具 → 导入项目 → 选择目录 `D:\Workspace\医保智审规则库\miniprogram\`
- 选择"不勾选合法域名" → 立即能看到 Hello World

### 3. 后端 HTTPS
详见根目录 `OVERVIEW.md §三`。
开发期勾"不校验合法域名"即可跳过后端域名检查。

### 4. 测试拉数据
- 打开网络面板，应该能看到 `/api/stats`、`/api/search` 等请求
- 没有数据？检查：
  1. `utils/config.js` 的 `apiBase` 是否正确
  2. 后端有没有跑（`/c/Python314/python.exe -m webapp.app`）
  3. HTTPS 是否就绪

---

## 🎨 设计系统：Clinical Clarity v2

| Token | 值 | 用途 |
|---|---|---|
| `--c-primary` | `#0284C7` | 主色 — 行动按钮 / 链接 |
| `--c-accent`  | `#0D9488` | 辅色 — 操作辅助 |
| `--c-cat-hc`  | `#2563EB` | 耗材 |
| `--c-cat-yp`  | `#059669` | 药品 |
| `--c-cat-ivd` | `#7C3AED` | 试剂 |
| `--c-cat-icd` | `#DC2626` | ICD |
| `--c-cat-ms`  | `#D97706` | 医疗服务 |
| `--c-cat-tcm` | `#0891B2` | 中医 |

完整 token 在 `app.wxss` 顶部 `:root` 段落。新增样式请优先用 token，不要硬编码颜色。

---

## 🔁 复用 FlASK 后端 API

| 页面 | 调用 | 后端接口 |
|---|---|---|
| 首页 | `GET /api/stats` | ✅ 已补 |
| 搜索 | `GET /api/search?q=&page=` | ✅ 已有 |
| 搜索代码表 | `GET /api/search/{yp\|hc\|tcm\|icd\|ivd\|ms}?q=` | ✅ 已有 |
| 详情 | `GET /api/kp/<id>` | ✅ 已有 |
| 编码反查 | `GET /api/code/<code>` | ✅ 已有 |

---

## 📋 上线前 Checklist（Stage 1.4）

- [ ] AppID 替换
- [ ] 服务器域名白名单（开发→开发设置→服务器域名）
- [ ] 隐私协议弹窗（基础库 ≥ 3.0.1 强制）
- [ ] 体验评分 ≥ 90（开发者工具→Audits）
- [ ] 个人主体 vs 企业主体 → 类目选择正确
- [ ] ICP 备案号（小程序后台填写）
- [ ] 提交审核，类目建议"医疗 > 医疗信息查询"（需企业主体）

---

## 🧱 后续路线图

- 阶段 2：收藏 / 历史 / 分享 / 扫码 / 订阅消息
- 阶段 3：AI 问答 / 视频号联动 / 公众号导流 / 广告位
- 详细路线图见 根目录 `OVERVIEW.md`

---

## 🆘 常见问题

**Q: 开发者工具报"不在以下 request 合法域名列表中"？**
A: 开发期请勾选开发者工具右上角「详情 → 本地设置 → 不校验合法域名」。

**Q: tabBar 上看不到图标？**
A: 小程序原生 tabBar 不支持 SVG。第一版先不做图标（纯文字），V1.1 再用 PNG。

**Q: Skyline 渲染引擎报错？**
A: 基础库需 ≥ 3.0.1。在 `project.config.json` 设 `"libVersion": "3.4.0"` 强制升级。
   若报错兼容，可临时把 `app.json` 的 `"renderer": "skyline"` 改成 `"webview"`。
