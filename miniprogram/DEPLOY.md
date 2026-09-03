# 医保智审规则库 · 微信小程序上线操作手册

> 文档版本：v1.0 · 2026-07-14
> 适用对象：项目负责人 / 运维 / 运营 / 任何要提审发布的人
> 预计完成时间：3-5 个工作日（最关键卡点是域名 ICP 备案 7-20 天）

---

## 0. 准备清单

| 资源 | 用途 | 谁申请 | 备注 |
|---|---|---|---|
| **小程序 AppID** | 唯一标识，所有 API 调用的身份凭证 | Sir | mp.weixin.qq.com 注册 |
| **小程序主体** | 企业 / 个人；决定类目是否可选「医疗」 | Sir | **企业主体**才能选医疗类目 |
| **ICP 备案过的子域名** | 例如 `api.yibao-zs.cn`，HTTPS 必备 | Sir | 阿里云/腾讯云 7-20 天 |
| **腾讯云 SSL 证书** | HTTPS 证书 | Sir | 腾讯云免费版或 Let's Encrypt |
| **服务器 SSH 凭据** | 部署 Nginx + 反代 | Sir | 已有 **132.232.152.250**（SSH 端口 **2222**，用户 `ubuntu`） |
| **小程序图标（PNG）** | tabBar + 启动图 | 设计/我 | V1.1 加，先纯文字 tabBar |
| **客服微信号** | 挂「联系客服」按钮 | Sir | 已复制：yibao-zs |

---

## 1. 后端 HTTPS 部署（约 1-2 小时）

### 1.1 申请 SSL 证书（选其一）

**A. 腾讯云免费证书（推荐，国内访问快）**
```
登录 console.cloud.tencent.com → SSL 证书 → 申请免费证书
域名填: api.yibao-zs.cn
验证方式: DNS（解析一条 TXT 记录）
下载格式: Nginx
下载后得到: fullchain.pem + privkey.pem
```

**B. Let's Encrypt（最快，无需账号）**
```bash
ssh -p 2222 ubuntu@132.232.152.250
sudo apt update && sudo apt install -y nginx certbot python3-certbot-nginx
sudo certbot --nginx -d api.yibao-zs.cn
# 证书自动续期
```

### 1.2 配置 Nginx 反代

```bash
# 上传证书到服务器（注意：SSH 端口是 2222，不是 22）
scp -P 2222 fullchain.pem ubuntu@132.232.152.250:/tmp/
scp -P 2222 privkey.pem    ubuntu@132.232.152.250:/tmp/
ssh -p 2222 ubuntu@132.232.152.250
sudo mv /tmp/fullchain.pem /etc/nginx/certs/api.yibao-zs.cn.crt
sudo mv /tmp/privkey.pem    /etc/nginx/certs/api.yibao-zs.cn.key
sudo chmod 600 /etc/nginx/certs/api.yibao-zs.cn.key
```

```nginx
# /etc/nginx/sites-available/api.yibao-zs.cn
server {
    listen 80;
    server_name api.yibao-zs.cn;
    return 301 https://$server_name$request_uri;  # 强制 HTTPS
}

server {
    listen 443 ssl http2;
    server_name api.yibao-zs.cn;

    ssl_certificate     /etc/nginx/certs/api.yibao-zs.cn.crt;
    ssl_certificate_key /etc/nginx/certs/api.yibao-zs.cn.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;

    # gzip
    gzip on;
    gzip_types application/json text/plain text/css;
    gzip_min_length 256;

    # 安全 headers（可选）
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options SAMEORIGIN;

    # 健康检查
    location = /healthz {
        return 200 "ok\n";
        add_header Content-Type text/plain;
    }

    # 反代到 Flask
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 30s;
        proxy_connect_timeout 5s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/api.yibao-zs.cn /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 1.3 验收

```bash
# 1. HTTPS 可达
curl -I https://api.yibao-zs.cn/api/stats
# 期望: HTTP/2 200

# 2. 真实数据
curl -s https://api.yibao-zs.cn/api/stats | python -m json.tool
# 期望: 看到 KP 21,935 / Rules 79 等

# 3. SSL 链完整（用 SSL Labs 或 openssl）
openssl s_client -connect api.yibao-zs.cn:443 -servername api.yibao-zs.cn < /dev/null | grep "Verify return code"
# 期望: 0 (ok)
```

---

## 2. 微信小程序后台配置（约 30 分钟）

### 2.1 拿到 AppID 后

1. 编辑 `miniprogram/project.config.json`，把 `"appid": "touristappid"` 改成真实 AppID
2. 在小程序后台 → 开发 → 开发设置 → **服务器域名**
   - request 合法域名：`https://api.yibao-zs.cn`
   - uploadFile 合法域名：（暂不填）
   - downloadFile 合法域名：（暂不填）

### 2.2 设置小程序基本信息
- 名称：`医保智审`
- 简称：`医保智审`
- 简介：`为医保审核员 / 编码员提供规则检索与编码反查`
- 头像：1024×1024 PNG（需要设计师/我生成）
- 类目：**医疗 → 医疗信息查询**（需企业主体）
- 标签：医保审核、医疗工具、信息查询

### 2.3 ICP 备案
- 小程序后台 → 设置 → 基本设置 → **ICP 备案**
- 填主体 ICP 备案号（与子域名一致）

---

## 3. 后端生产环境变量

服务器上：
```bash
# 编辑 Flask 启动服务（systemd 或 supervisor）
sudo -e /etc/systemd/system/medical-audit.service
```

```ini
[Unit]
Description=Medical Audit Flask
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/opt/medical-audit
Environment="WECHAT_APPID=wx_your_actual_appid"
Environment="WECHAT_SECRET=wx_your_actual_secret"
Environment="MA_TOKEN_SALT=你的随机 32 位 salt（openssl rand -hex 16）"
ExecStart=/usr/bin/python3 -m gunicorn -w 2 -b 127.0.0.1:5000 webapp.app:app
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now medical-audit
sudo systemctl status medical-audit  # 验证 running
```

---

## 4. 体验评分自查（Audits）

打开微信开发者工具 → Audits 面板 → 勾选「自动运行」

**目标：≥ 90 分**（最低过审线 80）

### 4.1 常见扣分项 + 修复

| 扣分项 | 原因 | 修复 |
|---|---|---|
| 启动耗时 > 1.5s | 主包过大 / 启动时同步请求 | `utils/request.js` 用异步；首页 onShow 调 stats 不要在 onLoad 同步 |
| setData 频率高 | 列表 onReachBottom 频繁 setData | 用 throttle；分页用虚拟列表 |
| WXML 节点 > 1000 | 一次渲染太多 | `wx:key` + `recycle-view` 优化列表 |
| 图片未 lazyload | `<image>` 没 `lazy-load` | 全部 `<image>` 加 `lazy-load="{{true}}"` |
| HTTPS 异常 | 用了 IP / HTTP | 检查 `utils/config.js` 全是 https |
| 隐私 API 缺失 | 没调 `wx.getPrivacySetting` | `app.js` 已调；检查 pages/privacy 入口可达 |
| 无效 CSS | 写了但没用的样式 | 删 wxml 里没引用的 wxss |

### 4.2 在 DevTools 里手动跑

1. 顶部菜单 → 工具 → **Audits**
2. 勾选所有项 → 运行
3. 等 30 秒 → 看报告
4. 重点看 **「最佳实践 / 体验 / 性能」** 三项分别 ≥ 90

---

## 5. 提审材料清单

### 5.1 上传审核前的准备
- [ ] 类目：**医疗 → 医疗信息查询**（如个人主体无医疗类目，换「工具 → 信息查询」）
- [ ] 服务类目证明（如类目要求）：
  - 增值电信业务经营许可证（如选「医疗服务」类目）
  - 医疗机构执业许可证（医疗器械相关）
- [ ] 隐私协议：`pages/privacy/privacy` 内容已审核
- [ ] 用户协议：`pages/about/about` 有备案号
- [ ] 客服微信号：可联系（挂上「意见反馈」button）
- [ ] 测试账号：如审核员要测某些受保护功能（V1 不需要）

### 5.2 自审过一遍

```bash
# 检查所有 API 调用是否走 HTTPS
grep -r "http://" miniprogram/ --include="*.js" --include="*.json"
# 期望：无结果（除注释）

# 检查敏感权限是否声明
grep -E "wx\.(scanCode|getLocation|chooseMedia|openLocation)" miniprogram/ -r
# 当前仅 scanCode，已在 pages/code-lookup/code-lookup.js 调
# 注意：scanCode 不需要 scope.userLocation 等
```

### 5.3 常见拒绝原因与应对

| 拒绝原因 | 修复方案 |
|---|---|
| 「服务类目与功能不符」 | 选「工具 → 信息查询」而不是「医疗」 |
| 「缺少隐私协议」 | 已做（pages/privacy/privacy） |
| 「域名未备案」 | 必须 ICP 备案，备案号填到后台 |
| 「测试账号无法登录」 | 当前不需要，提供测试说明即可 |
| 「含有医疗建议/诊断」 | 详情页加一句免责声明；本工具仅供审核员参考 |
| 「URL/二维码违规」 | 详情页移除所有外部链接 |
| 「类目资质不全」 | 个人主体建议先选「工具」类目，企业主体再升级 |

---

## 6. 上线步骤（按顺序）

```
Day 0: 申请 AppID + 备案域名（耗时 1-3 天）
Day 1: 部署 HTTPS + 配置 Nginx
Day 2: 配置小程序后台域名白名单 + 替换 project.config.json 的 appid
Day 3: 开发者工具真机扫码 → 体验评分自查
Day 4: 提审 → 等待 1-3 天过审
Day 5: 🎉 发布！
```

### 6.1 真机测试清单

在微信开发者工具里点「预览」 → 拿手机微信扫码 → 检查：

- [ ] 首页能加载数据（stats + recent）
- [ ] 搜索 "糖尿病" 能命中
- [ ] 切换 7 个 tab 都正常
- [ ] 编码反查输入 `XK00000123456789` 能查询
- [ ] 扫码识别编码能用
- [ ] 详情页能看编码列表 + 关联规则
- [ ] 分享好友 / 朋友圈 标题显示正确
- [ ] 隐私协议页同意后能正常返回
- [ ] 4G / WiFi 切换不卡顿

---

## 7. 上线后运营（Stage 2）

### 7.1 留存功能（V1.1）

| 模块 | 工期 | 预期效果 |
|---|---|---|
| 我的收藏（本地 + 后端） | 1 天 | 7 日回访率 +15% |
| 最近浏览历史 | 0.5 天 | 与收藏合并 |
| 扫码查码增强 | 0.5 天 | 用药盒条码反查厂家 |
| 客服消息（button open-type="contact"） | 0.3 天 | 用户反馈通道 |
| 订阅消息（政策更新推送） | 1 天 | 用户触达复访 |

### 7.2 增长引擎（V1.2）

| 模块 | 关键 KPI |
|---|---|
| 自定义搜索关键词（小程序后台） | 微信搜索 UV |
| sitemap 提交 | 索引量 |
| 视频号绑定 + 短视频种草 | 转化率 |
| 公众号关联（双向跳转） | 私域引流 |
| 广告位开通（流量主 > 1000 UV） | 变现 |

---

## 8. 应急处理

### 8.1 服务挂了
```bash
ssh -p 2222 ubuntu@132.232.152.250
sudo systemctl status medical-audit
sudo systemctl restart medical-audit
sudo tail -f /var/log/medical-audit.log
```

### 8.2 接口报错增多
```bash
# 看最近 100 条 /api/stats 请求
sqlite3 webapp/data/kp.db "SELECT * FROM mini_app_events WHERE event LIKE 'page_view%' ORDER BY t DESC LIMIT 100"
```

### 8.3 审核被拒
1. 截屏审核反馈
2. 找共同原因（参考 §5.3）
3. 修改后重新提审（一次最多 3 次）

---

## 9. 联系信息（提审时填）

| 项 | 内容 |
|---|---|
| 客服微信 | yibao-zs |
| 邮箱 | yacaofeng@qq.com |
| 服务类目 | 工具 → 信息查询（建议） / 医疗 → 医疗信息查询（企业主体） |
| 数据来源 | 国家医保局 NHSA + 各省政策 PDF |

---

**最后更新**：2026-07-14
**下次更新**：Stage 1.4 完成时（提审通过后）