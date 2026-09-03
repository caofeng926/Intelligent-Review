# 医保智审规则库 · 微信小程序实施总览

> 一个面向 B 端 + G 端的医保审核规则检索工具，把现有 Flask 后端搬上微信生态。
> 目标：**最快 1 周发版上线，先验证需求，再加速增长**。

---

## 一、为什么值得做

| 优势 | 现状 |
|---|---|
| 数据真实、独家 | 79 规则 / 21,935 知识点 / 8.7 万耗材 / 26 万药品，是医保审核员的真实工具 |
| 后端基本可用 | Flask API 已就绪，仅缺 HTTPS 与前端重写 |
| 微信天然适配 | 工具类小程序最轻、最快、最容易拿到微信搜索免费流量 |
| 复用设计系统 | 已有 `Clinical Clarity v2` 主题（#0284C7 + #0D9488）可直接复用 |

---

## 二、路线图（7 个 Stage）

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Stage 0  HTTPS + 域名白名单                              ⏱ 当天       │
│          ├ 腾讯云免费 SSL 证书                                                │
│          ├ Nginx 反代 443 → 5000                                            │
│          └ 微信小程序后台加 request 合法域名                                │
│                                                                           │
│  Stage 1  MVP 5 页上线（先有，再完美）                       ⏱ 3-4 天    │
│          ├ ①骨架 + AppID + request 封装                                      │
│          ├ ②首页 / 搜索 / 详情 / 编码反查 / 分类                              │
│          ├ ③tabBar + 加载/空/错状态                                          │
│          └ ④privacy 协议 + wx.getPrivacySetting + 体验评分                   │
│                                                                           │
│  🎉     【第一次发版上线】                                                  │
│                                                                           │
│  Stage 2  个人中心与留存                                    ⏱ 3 天      │
│          ├ 收藏 / 历史 / 分享 / 扫码 / 客服 / 订阅消息                          │
│          └ wx.login → 拿 openid 做用户画像                                     │
│                                                                           │
│  Stage 3  增长引擎                                           ⏱ 持续     │
│          ├ 搜索 SEO（自定义关键词 + sitemap）                                 │
│          ├ 视频号 + 公众号 联动                                               │
│          ├ 广告组件（banner / 激励视频）                                       │
│          └ 数据分析（wx.reportMonitor + 自定义埋点）                           │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 三、Stage 0 详细方案：HTTPS + 域名白名单

### 0.1 阻塞项（必须先解决）
- [ ] **小程序 AppID**（注册: https://mp.weixin.qq.com/）
- [ ] **已 ICP 备案的子域名**，例如 `api.yibao-zs.cn`

### 0.2 服务器端（腾讯云 CVM `132.232.152.250`，SSH 端口 2222）

```bash
# 0. SSH 到服务器（端口 2222，不是 22）
ssh -p 2222 ubuntu@132.232.152.250

# 1. 装 Nginx（已装 Nginx 1.24.0，跳过）
# sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx

# 2. 写反代配置（注意 80 已经被"中国旅游地图"占用，建议绑新 server_name）
sudo tee /etc/nginx/sites-available/yibao-zs << 'EOF'
server {
    listen 443 ssl;
    server_name api.yibao-zs.cn;

    ssl_certificate /etc/letsencrypt/live/api.yibao-zs.cn/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.yibao-zs.cn/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    gzip on;
    gzip_types application/json text/css;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 30s;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/yibao-zs /etc/nginx/sites-enabled/

# 3. 申请证书（Let's Encrypt 免费）
sudo certbot --nginx -d api.yibao-zs.cn

# 4. 启动 / 重载
sudo nginx -t && sudo systemctl reload nginx
```

### 0.3 微信小程序后台
- 登录 https://mp.weixin.qq.com/
- 开发 → 开发设置 → 服务器域名
  - request 合法域名：`https://api.yibao-zs.cn`
  - uploadFile 合法域名：暂不填（V1 没文件上传）
  - downloadFile 合法域名：暂不填

### 0.4 验收
```bash
curl -s "https://api.yibao-zs.cn/api/search?q=糖尿病" | head -c 200
# 期望：返回 JSON 数组，不是 SSL 错误
```

---

## 四、Stage 1 详细方案：5 页 MVP

### 4.1 项目目录（原生 WXML/WXSS/JS）
```
miniprogram/
├── app.js                  # App 生命周期 + 全局数据
├── app.json                # 全局配置（pages, tabBar, window, permission）
├── app.wxss                # 全局样式（Clinical Clarity v2 主题）
├── sitemap.json            # 微信搜索索引
├── project.config.json     # 项目配置（AppID、Skyline 渲染）
├── project.private.config.json  # 本地私有配置（忽略 git）
├── utils/
│   ├── request.js          # 统一请求封装（Promise + 拦截器）
│   ├── config.js           # API 基地址
│   ├── storage.js          # 本地存储（wx.setStorageSync 封装）
│   └── format.js           # 数据格式化（日期、字符截断）
├── components/
│   ├── kp-card/            # 知识点列表卡片
│   ├── empty-state/        # 空状态
│   └── loading/            # 加载态
├── pages/
│   ├── index/              # 首页（数据卡片 + 入口宫格）
│   ├── search/             # 搜索（6 tab 切换）
│   ├── kp-detail/          # 知识点详情
│   ├── code-lookup/        # 编码反查
│   ├── category/           # 分类浏览
│   ├── privacy/            # 隐私协议（合规用）
│   └── about/              # 关于（备案号、版权）
└── README.md
```

### 4.2 utils/request.js（核心）
```javascript
const { API_BASE } = require('./config');

function request(options) {
  return new Promise((resolve, reject) => {
    const token = wx.getStorageSync('access_token');
    wx.request({
      url: API_BASE + options.url,
      method: options.method || 'GET',
      data: options.data,
      header: {
        'Content-Type': 'application/json',
        ...(token && { Authorization: `Bearer ${token}` }),
        ...options.header,
      },
      timeout: 15000,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
        } else if (res.statusCode === 404) {
          reject({ code: 404, message: '资源不存在' });
        } else {
          reject({ code: res.statusCode, message: res.data?.message || '请求失败' });
        }
      },
      fail: (err) => reject({ code: -1, message: '网络异常', detail: err }),
    });
  });
}

module.exports = { request };
```

### 4.3 5 个页面接口映射

| 页面 | 调用 API | 备注 |
|---|---|---|
| `pages/index` | `GET /api/stats`（新增聚合接口，返回 KP / Rules / HC / YP / TCM / ICD / MS 的条数） | 首屏最重要 |
| `pages/search` | `GET /api/search?q=&mode=&source=&page=` | 已有！复用 |
| `pages/kp-detail` | `GET /api/kp/<id>` | 已有！复用 |
| `pages/code-lookup` | `GET /api/code/<code>` | 已有！复用 |
| `pages/category` | `GET /api/code/<code>` 的 6 个代码表 | 拼装已有接口 |

> **复用率 80%**，仅 `index` 页面需要后端补一个 `GET /api/stats` 聚合接口。

### 4.4 设计系统（直接复用 web 端 `Clinical Clarity v2`）

```css
/* app.wxss */
page {
  --c-primary: #0284C7;
  --c-primary-dark: #0369A1;
  --c-accent: #0D9488;
  --c-surface: #FFFFFF;
  --c-bg: #F8FAFC;
  --c-border: #E2E8F0;
  --c-text: #0F172A;
  --c-text-muted: #64748B;

  --c-cat-hc:   #2563EB;
  --c-cat-ivd:  #7C3AED;
  --c-cat-yp:   #059669;
  --c-cat-icd:  #DC2626;
  --c-cat-ms:   #D97706;
  --c-cat-tcm:  #0891B2;

  background: var(--c-bg);
  color: var(--c-text);
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif;
  font-size: 28rpx;
}
```

### 4.5 后端待补：轻量聚合接口 `GET /api/stats`
```python
# webapp/app.py 末尾追加
@app.get("/api/stats")
def api_stats():
    with db.connect() as conn:
        return jsonify({
            "knowledge_points": conn.execute("SELECT COUNT(*) FROM knowledge_points").fetchone()[0],
            "codes": conn.execute("SELECT COUNT(*) FROM knowledge_point_codes").fetchone()[0],
            "rules": conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0],
            "nhsa_rules": conn.execute("SELECT COUNT(*) FROM rules WHERE source='nhsa_batch'").fetchone()[0],
            "consumables": conn.execute("SELECT COUNT(*) FROM consumable_codes").fetchone()[0],
            "yp_2025": _safe_count(conn, "yp_catalog_2025"),
            "tcm": _safe_count(conn, "tcm_codes"),
            "icd": _safe_count(conn, "icd_codes"),
            "ivd": _safe_count(conn, "ivd_codes"),
            "ms": _safe_count(conn, "medical_service_codes"),
        })
```

### 4.6 体验评分自查（上线前 ≥ 90 分）
- [ ] 首屏时间 < 1.5s（首页缓存 + skeleton）
- [ ] setData 频率合理（debounce）
- [ ] 图片懒加载 + 合理尺寸
- [ ] 启用 Skyline 渲染引擎（project.config.json → `setting.checkInvalidKey: false`、`libVersion: 3.x`）
- [ ] 全部 HTTPS
- [ ] 无废弃接口
- [ ] 及时回收定时器
- [ ] WXML 节点数 < 1000/屏

---

## 五、Stage 2-3 关键模块

### Stage 2：留存（3 天）

| 模块 | API/能力 | 工时 |
|---|---|---|
| 收藏 | `wx.setStorageSync('favs', [...])` 纯本地 | 0.5d |
| 搜索历史 | 同上 | 0.3d |
| 分享好友 | `onShareAppMessage()` | 0.3d |
| 分享朋友圈 | `onShareTimeline()` | 0.2d |
| 扫码查码 | `wx.scanCode` → 跳转到 code-lookup | 0.5d |
| 客服消息 | `<button open-type="contact">` | 0.2d |
| 订阅消息 | 政策更新推送（用户授权后） | 1d |

### Stage 3：增长（持续）

- **微信搜索 SEO**：在 `app.json` 中加 `permission.scope.userLocation` 等 + 后台"自定义关键词"
- **sitemap.json** 提交搜索
- **视频号绑定** + 短视频种草
- **广告组件**：开通流量主（>1000 UV 后）
- **数据分析**：自定义埋点 + `wx.reportMonitor`

---

## 六、阻塞项清单（上线前必须就绪）

| 阻塞 | 谁负责 | 状态 |
|---|---|---|
| 微信小程序 AppID | 用户注册 | ⏳ 待申请 |
| ICP 备案过的子域名（如 `api.yibao-zs.cn`） | 用户申请 | ⏳ 待申请 |
| 腾讯云免费 SSL 证书 | 用户下载或自动 Let’s Encrypt | ⏳ 待申请 |
| 服务器 SSH 访问 | 用户授权 | ✅ 已有（132.232.152.250，端口 2222，2026-07-18 实测） |
| 小程序类目（医疗/工具）| 提审时填 | ⏳ 待选 |
| 内容合规自查（医保政策不违规） | 用户审阅 | ⏳ 待确认 |

---

## 七、下一步建议

**先做**（今天）：写出 `utils/request.js` + `app.json` + 骨架，让小程序能在开发者工具里跑起来 Hello World，**不等 HTTPS**（开发时可勾"不校验域名"）。

**接着**（明天-后天）：HTTPS + AppID + 域名白名单打通。

**然后**（3-5 天）：5 个页面一页一页实现，每天至少发一个体验版给自己扫一扫。

**最后**（5-7 天）：privacy 协议 + 体验评分 + 提审。

---

> 维护者：医保智审规则库 · 项目长期记忆见 `D:\Workspace\医保智审规则库\.workbuddy\memory\MEMORY.md`
