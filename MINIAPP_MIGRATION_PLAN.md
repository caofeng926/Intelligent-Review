# 医保智审规则库 — 微信小程序迁移计划

> 基于 Flask + SQLite Web 应用的完整功能盘点，制定小程序化迁移方案。
> 编制日期：2026-07-07

---

## 一、现状盘点

### 1.1 技术栈

| 维度 | 现状 | 小程序要求 |
|---|---|---|
| 前端 | Jinja2 HTML (40 模板) + CSS (2339 行) + JS (252 行) | WXML + WXSS + JS |
| 后端 | Flask + SQLite (415MB) | 保持 Flask，新增 JSON API |
| 部署 | `http://43.136.175.219:5000` | **必须 HTTPS** + 域名白名单 |
| 数据库 | 415MB SQLite，不可打包进小程序 | 纯服务端 API 驱动 |
| 已有 AppID | `wx19197367f661c1a3` | ✅ 可用 |

### 1.2 功能模块清单

| 模块 | 路由 | JSON API 已有？ | 模板数 | 迁移优先级 |
|---|---|---|---|---|
| 首页/统计 | `/` | ❌ 仅 HTML | 1 | P0 |
| 知识点搜索 | `/search` + `/api/search` | ✅ | 1 | P0 |
| 知识点详情 | `/kp/<id>` + `/api/kp/<id>` | ✅ | 1 | P0 |
| 代码表搜索 (6种) | `/search/{yp,hc,tcm,icd,ivd,ms}` | ❌ | 1(共用) | P0 |
| 规则分类浏览 | `/rules/category` + `/api/rule-categories` | ✅ | 1 | P1 |
| 规则列表 | `/rules/list` | ❌ | 1 | P1 |
| 按知识点查规则 | `/rules/find` | ❌ | 1 | P1 |
| 规则详情 | `/rules/<id>` | ❌ | 1 | P1 |
| 耗材浏览 | `/consumables` (3级下钻) | ✅ categories | 2 | P1 |
| 耗材详情 | `/consumables/code/<code>` | ✅ | 1 | P1 |
| 编码反查 | `/api/code/<code>` | ✅ | — | P0 |
| 跨表反查 | `/api/code2/<code>` | ✅ | — | P0 |
| NHSA 药品(YP) | `/nhsa/yp` + `/api/nhsa/yp/*` | ✅ | 2 | P1 |
| NHSA 耗材(HC) | `/nhsa/hc7` + `/api/nhsa/hc7/*` | ✅ | 2 | P1 |
| NHSA 诊断(IVD) | `/nhsa/ivd` + `/api/nhsa/ivd/*` | ✅ | 2 | P1 |
| NHSA ICD-10 | `/nhsa/icd` + `/api/nhsa/icd/*` | ✅ | 2 | P1 |
| NHSA 医疗服务(MS) | `/nhsa/ms` + `/api/nhsa/ms/*` | ✅ | 2 | P1 |
| NHSA 中药(TCM) | `/nhsa/tcm` + `/api/nhsa/tcm/*` | ✅ | 2 | P1 |
| 陕西版医疗服务 | `/nhsa/sn_ms` | ❌ | 2 | P2 |
| 2023版药品目录 | `/yp2023` | ❌ | 2 | P2 |
| 管理后台 | `/admin/*` | ❌ | 12 | **不迁移** |
| **合计** | | 15/30 有 API | 40→28 迁移 | |

### 1.3 已有 JSON API 端点（可直接复用）

```
GET /api/search?q=&mode=&source=&page=&limit=
GET /api/kp/<id>
GET /api/code/<code>
GET /api/code2/<code>
GET /api/consumable/<code>
GET /api/consumable-categories?l1=&l2=
GET /api/rule-categories
GET /api/nhsa/stats
GET /api/nhsa/yp/search?q=&limit=
GET /api/nhsa/yp/code/<code>
GET /api/nhsa/yp/approval/<no>
GET /api/nhsa/ivd/search?q=&limit=
GET /api/nhsa/ivd/code/<code>
GET /api/nhsa/icd/search?q=&limit=
GET /api/nhsa/icd/code/<code>
GET /api/nhsa/ms/search?q=&limit=
GET /api/nhsa/ms/code/<code>
GET /api/nhsa/tcm/search?q=&limit=
GET /api/nhsa/tcm/code/<code>
GET /api/nhsa/hc7/code/<code>
```

### 1.4 需要新增的 JSON API 端点

```
GET /api/home/stats              — 首页统计数据
GET /api/rules?q=&page=          — 规则列表
GET /api/rules/<id>?page=        — 规则详情 + KP 列表
GET /api/rules/find?q=&source=   — 按知识点查规则
GET /api/search/yp?q=&page=      — 药品代码搜索
GET /api/search/hc?q=&page=      — 耗材代码搜索
GET /api/search/tcm?q=&page=     — 中药代码搜索
GET /api/search/icd?q=&page=     — ICD 搜索
GET /api/search/ivd?q=&page=     — 试剂搜索
GET /api/search/ms?q=&page=      — 服务搜索
GET /api/sn_ms/search?q=         — 陕西服务搜索
GET /api/sn_ms/sheet/<sheet>     — 陕西服务浏览
GET /api/sn_ms/code/<code>       — 陕西服务详情
GET /api/yp2023/list?cat=&page=  — 2023目录列表
GET /api/yp2023/detail?name=     — 2023目录详情
```

---

## 二、架构方案

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────┐
│                微信小程序 (前端)                       │
│  WXML + WXSS + JS + 自定义组件                        │
│  主包 (<2MB) + 分包 (业务页面)                        │
└──────────────────────┬──────────────────────────────┘
                       │ HTTPS (wx.request)
                       ▼
┌─────────────────────────────────────────────────────┐
│              Flask 后端 (API 层)                      │
│  43.136.175.219 (Nginx + SSL + Gunicorn)             │
│  /api/* — 纯 JSON 响应                                │
│  现有 HTML 路由保留 (Web 端继续可用)                   │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              SQLite 数据库 (415MB)                    │
│  现有表结构不变，仅新增 API 读取层                     │
└─────────────────────────────────────────────────────┘
```

### 2.2 小程序分包策略

```
主包 (<2MB)
├── pages/index/          首页
├── pages/search/         统一搜索入口
├── pages/kp-detail/      知识点详情
├── pages/rule-detail/    规则详情
├── pages/code-detail/    编码详情 (通用，按 kind 分支)
├── components/           公共组件
├── utils/                工具函数
└── app.json / app.js / app.wxss

分包A: rules (规则模块)
├── pages/rules/category/
├── pages/rules/list/
└── pages/rules/find/

分包B: nhsa (NHSA 编码库)
├── pages/nhsa/yp/
├── pages/nhsa/hc/
├── pages/nhsa/ivd/
├── pages/nhsa/icd/
├── pages/nhsa/ms/
├── pages/nhsa/tcm/
└── pages/nhsa/sn-ms/

分包C: catalog (2023目录)
└── pages/catalog/list/
└── pages/catalog/detail/
```

### 2.3 页面映射表

| Web 页面 | 小程序页面 | 备注 |
|---|---|---|
| `/` (home.html) | `pages/index/index` | 统计卡片 + 快捷入口 |
| `/search` (search.html) | `pages/search/search` | 统一搜索，6 个 tab |
| `/kp/<id>` (kp.html) | `pages/kp-detail/kp-detail` | KP 详情 |
| `/rules/category` | `pages/rules/category` | 分包 A |
| `/rules/list` | `pages/rules/list` | 分包 A |
| `/rules/find` | `pages/rules/find` | 分包 A |
| `/rules/<id>` | `pages/rule-detail/rule-detail` | 主包 |
| `/search/yp` | `pages/search/yp` | 复用 search 组件 |
| `/search/hc` | `pages/search/hc` | |
| `/nhsa/yp` | `pages/nhsa/yp` | 分包 B |
| `/nhsa/yp/code/<code>` | `pages/code-detail/code-detail?kind=yp` | 通用详情 |
| `/consumables` | `pages/nhsa/hc` | 分包 B |
| `/consumables/code/<code>` | `pages/code-detail?kind=hc` | |
| `/admin/*` | **不迁移** | 保持 Web 端 |

---

## 三、分阶段实施计划

### 阶段 0：基础设施准备（前置条件）

| 序号 | 任务 | 说明 |
|---|---|---|
| 0.1 | HTTPS 配置 | 腾讯云 CVM 配置域名 + Nginx 反向代理 + SSL 证书（可用 Let's Encrypt 免费证书或腾讯云免费证书） |
| 0.2 | 域名备案 | 小程序要求服务器域名已备案；如果 43.136.175.219 对应域名未备案，需先完成 |
| 0.3 | 微信后台配置 | 在小程序管理后台 → 开发管理 → 服务器域名，添加 `https://your-domain.com` 到 request 合法域名 |
| 0.4 | Nginx 反向代理 | `https://domain → http://127.0.0.1:5000`，处理 SSL 终止 + 静态资源缓存 |
| 0.5 | Gunicorn 部署 | 替换 `app.run()`，用 `gunicorn -w 4 -b 127.0.0.1:5000 webapp.app:app` |

### 阶段 1：后端 API 补全（P0 功能）

| 序号 | 任务 | API | 对应现有路由 |
|---|---|---|---|
| 1.1 | 首页统计 API | `GET /api/home/stats` | `home()` |
| 1.2 | 代码表搜索 API × 6 | `GET /api/search/{yp,hc,tcm,icd,ivd,ms}` | `_code_route()` |
| 1.3 | 规则列表 API | `GET /api/rules?q=&page=` | `rules_list()` |
| 1.4 | 规则详情 API | `GET /api/rules/<id>?page=` | `rule_detail()` |
| 1.5 | 按知识点查规则 API | `GET /api/rules/find?q=&source=` | `rules_find()` |
| 1.6 | 统一搜索优化 | 现有 `/api/search` 增加分页元数据 | 已有，需增强 |
| 1.7 | API 统一响应格式 | 所有 API 返回 `{success, data, pagination, error}` 标准结构 | 新增中间件 |
| 1.8 | CORS 配置 | Flask-CORS 或 Nginx 层处理 | 小程序不需要 CORS，但 Web 端调试需要 |
| 1.9 | 速率限制 | `flask-limiter` 防止小程序端误刷 | 新增 |

### 阶段 2：小程序骨架 + P0 页面

| 序号 | 任务 | 说明 |
|---|---|---|
| 2.1 | 初始化项目 | `D:\Workspace\医保智审规则库\miniapp\`，配置 `app.json` / `project.config.json` |
| 2.2 | 全局样式 | `app.wxss` — 设计 token（天蓝 #0284C7 + 青色 #0D9488），从现有 `mobile.css` 提取 |
| 2.3 | 请求封装 | `utils/request.js` — 统一 wx.request，自动处理分页、错误、loading |
| 2.4 | 首页 | `pages/index/` — 统计卡片 + 6 个功能入口 + 最近更新 |
| 2.5 | 统一搜索页 | `pages/search/` — 6 tab 切换 (KP/YP/HC/TCM/ICD/IVD/MS)，输入框 + 结果列表 |
| 2.6 | 知识点详情 | `pages/kp-detail/` — KP 信息 + 编码列表 + 厂家信息 + 检测逻辑 |
| 2.7 | 规则详情 | `pages/rule-detail/` — 规则信息 + KP 分页列表 |
| 2.8 | 编码详情 | `pages/code-detail/` — 通用页面，按 `kind` 参数展示不同字段 |
| 2.9 | 编码反查 | 搜索页输入编码时自动调用 `/api/code2/<code>` 跨表查找 |

### 阶段 3：P1 功能页面

| 序号 | 任务 | 说明 |
|---|---|---|
| 3.1 | 规则分类浏览 | `pages/rules/category/` — 分包 A |
| 3.2 | 规则列表 | `pages/rules/list/` — 搜索 + 去重列表 |
| 3.3 | 按知识点查规则 | `pages/rules/find/` — 输入药品/项目名，列出涉及的规则 |
| 3.4 | 耗材 3 级浏览 | `pages/nhsa/hc/` — L1→L2→L3 下钻 |
| 3.5 | NHSA 药品浏览 | `pages/nhsa/yp/` — 分类筛选 + 搜索 |
| 3.6 | NHSA ICD 浏览 | `pages/nhsa/icd/` — 章节浏览 + 搜索 |
| 3.7 | NHSA 医疗服务 | `pages/nhsa/ms/` — 层级浏览 |
| 3.8 | NHSA 中药 | `pages/nhsa/tcm/` — 部位/层级浏览 |
| 3.9 | NHSA 诊断试剂 | `pages/nhsa/ivd/` — 检测类别浏览 |
| 3.10 | 7类耗材浏览 | `pages/nhsa/hc7/` — 搜索 + 列表 |

### 阶段 4：P2 功能 + 体验优化

| 序号 | 任务 | 说明 |
|---|---|---|
| 4.1 | 陕西版医疗服务 | `pages/nhsa/sn-ms/` — 8 sheet 浏览 + 4 级下钻 |
| 4.2 | 2023 版药品目录 | `pages/catalog/` — 分包 C |
| 4.3 | 搜索历史 | `utils/history.js` — 本地存储搜索记录 |
| 4.4 | 收藏功能 | 本地收藏常用编码/KP |
| 4.5 | 分享功能 | `onShareAppMessage` — 分享知识点/编码详情到微信 |
| 4.6 | 搜索建议 | 输入时联想（debounce + API） |
| 4.7 | 骨架屏 | 列表页加载时的占位动画 |
| 4.8 | 空状态 | 统一空结果组件 |
| 4.9 | 性能优化 | setData 批量更新、虚拟列表、图片懒加载 |

### 阶段 5：审核与发布

| 序号 | 任务 | 说明 |
|---|---|---|
| 5.1 | 隐私协议 | 小程序隐私政策页面 + 用户授权流程 |
| 5.2 | 体验测试 | 真机测试（iOS + Android） |
| 5.3 | 提审材料 | 类目选择（工具→信息查询），功能页面截图 |
| 5.4 | 提交审核 | 首次提审，预计 1-3 个工作日 |
| 5.5 | 发布上线 | 审核通过后全量发布或灰度 |

---

## 四、技术要点

### 4.1 CSS → WXSS 迁移策略

现有 `mobile.css` (2339 行) 的设计 token 体系可直接复用：

```wxss
/* app.wxss — 全局样式 */
page {
  --c-primary: #0284C7;
  --c-accent: #0D9488;
  --c-surface: #ffffff;
  --c-bg: #f8fafc;
  --c-border: #e2e8f0;
  --c-text: #1e293b;
  --c-text-secondary: #64748b;
  --radius-sm: 8rpx;
  --radius-md: 16rpx;
  --radius-lg: 24rpx;
}
```

**注意**：WXSS 不支持 `:root` 选择器，用 `page` 替代。`rpx` 替代 `px`（750rpx = 屏宽）。

### 4.2 搜索逻辑迁移

现有 FTS5 搜索在服务端，小程序端只需：
1. 用户输入 → debounce 300ms → `wx.request('/api/search?q=...')`
2. 结果分页 → 上拉加载更多
3. 模式自动检测（编码/拼音/名称）由服务端 `detect_mode()` 处理

### 4.3 6 种代码表搜索的统一处理

```javascript
// pages/search/search.js
const TABS = [
  { key: 'kp',  label: '审核规则', api: '/api/search' },
  { key: 'yp',  label: '医保药品', api: '/api/search/yp' },
  { key: 'hc',  label: '医用耗材', api: '/api/search/hc' },
  { key: 'tcm', label: '中医病证', api: '/api/search/tcm' },
  { key: 'icd', label: 'ICD-10',  api: '/api/search/icd' },
  { key: 'ivd', label: '诊断试剂', api: '/api/search/ivd' },
  { key: 'ms',  label: '医疗服务', api: '/api/search/ms' },
];
```

### 4.4 编码详情页的通用设计

现有 Web 端有 7 种编码详情页（YP/HC/HC7/IVD/ICD/MS/TCM），小程序用 1 个通用页面：

```javascript
// pages/code-detail/code-detail.js
// onLoad(options) → options.kind + options.code
// 根据 kind 选择不同的字段渲染模板 (WXML 条件渲染)
```

### 4.5 性能约束

| 约束 | 限制 | 应对策略 |
|---|---|---|
| 主包大小 | 2MB | 仅放首页+搜索+详情+公共组件 |
| 分包大小 | 2MB/个 | rules / nhsa / catalog 三个分包 |
| 总包大小 | 20MB | 足够，无图片资源 |
| setData 频率 | 尽量少 | 批量更新，不分条 setData |
| wx.request 并发 | 10 个 | 搜索+详情不会同时超限 |
| 列表渲染 | 100 条以内 | 分页 20 条/页 |

### 4.6 管理后台处理

**不迁移到小程序**，原因：
1. 管理后台 12 个模板，功能复杂（审计、同步、设置、政策查询）
2. 管理后台是内部使用，不需要移动端
3. 小程序审核对管理类功能限制较多

**方案**：保持 Web 端 `/admin/*` 不变，管理员通过浏览器访问。

---

## 五、工作量评估

| 阶段 | 内容 | 产出 | 复杂度 |
|---|---|---|---|
| 阶段 0 | HTTPS + 域名 + Nginx | 基础设施 | 低（运维操作） |
| 阶段 1 | 后端 API 补全 (15 个端点) | `webapp/api_v2.py` 新模块 | 中（大部分逻辑已有，加 JSON 输出） |
| 阶段 2 | 小程序骨架 + 6 个 P0 页面 | 主包 + 首页/搜索/详情 | 高（从零搭建） |
| 阶段 3 | P1 功能页面 (10 个页面) | 3 个分包 | 中（页面多但模式相似） |
| 阶段 4 | P2 功能 + 体验优化 | 扩展功能 | 中 |
| 阶段 5 | 审核与发布 | 上线 | 低 |

---

## 六、风险与注意事项

### 6.1 高风险项

| 风险 | 影响 | 应对 |
|---|---|---|
| 域名未备案 | 无法配置服务器域名，小程序无法发请求 | 立即启动备案流程（需 7-20 天） |
| HTTPS 证书 | 无证书则无法通过审核 | 腾讯云免费 SSL 证书，1 天搞定 |
| 415MB 数据库查询性能 | 小程序端搜索延迟 >3s 会被判定卡顿 | 已有 FTS5 索引，API 响应 <200ms |
| 微信审核类目 | 工具类小程序需选择正确类目 | "工具 → 信息查询" 最匹配 |

### 6.2 注意事项

1. **小程序不需要 CORS** — `wx.request` 不受同源策略限制，但域名必须在白名单
2. **本地开发** — 开发阶段可在微信开发者工具中关闭域名校验（详情 → 本地设置 → 不校验合法域名）
3. **API 版本** — 建议新 API 统一加 `/api/v2/` 前缀，与现有 API 隔离
4. **数据安全** — 现有 API 无鉴权，小程序端应加 `wx.login` + 服务端 session 校验（如果需要用户身份）
5. **搜索体验** — 小程序搜索框建议加搜索历史 + 热门搜索词
6. **TabBar** — 考虑底部 TabBar：首页 / 搜索 / 规则 / 我的

---

## 七、目录结构规划

```
D:\Workspace\医保智审规则库\
├── webapp/                     # 现有 Flask 后端 (保留)
│   ├── app.py
│   ├── api_v2.py              # 新增：小程序专用 API
│   ├── ...
│   └── data/kp.db
├── miniapp/                    # 新增：微信小程序
│   ├── app.js
│   ├── app.json
│   ├── app.wxss
│   ├── project.config.json
│   ├── sitemap.json
│   ├── pages/
│   │   ├── index/
│   │   ├── search/
│   │   ├── kp-detail/
│   │   ├── rule-detail/
│   │   └── code-detail/
│   ├── packageA/              # 规则模块分包
│   │   └── pages/rules/
│   ├── packageB/              # NHSA 编码库分包
│   │   └── pages/nhsa/
│   ├── packageC/              # 2023目录分包
│   │   └── pages/catalog/
│   ├── components/            # 公共组件
│   │   ├── search-bar/
│   │   ├── result-list/
│   │   ├── stat-card/
│   │   ├── empty-state/
│   │   └── code-tag/
│   ├── utils/
│   │   ├── request.js         # 统一请求封装
│   │   ├── search.js          # 搜索逻辑
│   │   └── format.js          # 格式化工具
│   └── images/                # 图标资源 (尽量少用)
└── ...
```

---

## 八、启动检查清单

在正式开发前，确认以下条件已满足：

- [ ] 腾讯云域名已购买并解析到 43.136.175.219
- [ ] 域名已备案（或已有备案域名可复用）
- [ ] SSL 证书已申请并配置
- [ ] Nginx 反向代理已配置（HTTPS → HTTP:5000）
- [ ] Gunicorn 已部署（替代 Flask dev server）
- [ ] 微信小程序管理后台已配置服务器域名
- [ ] 微信开发者工具已安装
- [ ] AppID `wx19197367f661c1a3` 可正常使用
- [ ] 现有 API 在 HTTPS 下可正常访问（浏览器验证）

---

## 九、总结

**核心判断**：这个项目的后端架构已经为小程序化做好了 50% 的准备——15+ 个 JSON API 已存在，FTS5 搜索在服务端，数据库不可打包但 API 响应快。

**最大工作量**：前端从零搭建（28 个页面 → WXML/WXSS），以及补全 15 个缺失的 API 端点。

**最大风险**：域名备案 + HTTPS 配置（行政流程，非技术难度）。

**建议路径**：先走阶段 0（基础设施），同步走阶段 1（API 补全），然后阶段 2（P0 页面）上线 MVP，再逐步补 P1/P2。
