# 医保智审服务器档案

> 文档目的：把所有关于服务器的事实、限制、待办决策点集中沉淀，方便 Sir 一次性 review。
> 状态：实测 + 待补充
> 最近更新：2026-07-18

---

## 1. 服务器清单（实测 2026-07-18）

### 1.1 主服务器（医保智审部署位置）

| 字段 | 值 | 实测 | 备注 |
|---|---|---|---|
| **公网 IP** | `132.232.152.250` | socket 已验证 | 腾讯云 CVM Ubuntu（推断轻量或 CVM） |
| **SSH 端口** | `2222` | OPEN | **不是默认 22** |
| **SSH 协议** | OpenSSH 9.6p1 Ubuntu-3ubuntu13.16 | banner 已抓 | Ubuntu 22.04+ |
| **SSH 用户** | `ubuntu`（推断） | 未验证 | 也可能是 root 或别的 |
| **22 端口** | CLOSED | 已测 | 防火墙挡了 |
| **OS** | Ubuntu Linux | 已测 | 内核版本待 SSH 进去查 |

### 1.2 端口全貌

| 端口 | 状态 | 服务 | 备注 |
|---|---|---|---|
| **80** | OPEN | Nginx 1.24.0 | 跑的是**"中国旅游地图"项目**，不是医保智审 |
| **443** | CLOSED | — | **没有 HTTPS**，小程序上线前必开 |
| **2222** | OPEN | OpenSSH | Sir 走这个登录 |
| **5000** | OPEN | gunicorn | 医保智审 web 端跑这里（旧版本，没 V1.1 mini-app 接口） |
| 21/22/3306/5432/6379/8000/8080/8888/9000 | CLOSED | — | FTP/SSH/DB/常见 web 都关 |

### 1.3 服务内容实测

#### Port 80 (Nginx)
```bash
$ curl http://132.232.152.250/
→ 返回 HTML doctype + "theme-color=#0284..." 蓝色
→ 实际内容：中国旅游地图（旅游统计 API 返回 {"total":11880,"scenic":3556,"food":8324}）
```

#### Port 5000 (gunicorn)
```bash
$ curl http://132.232.152.250:5000/
→ 返回 HTML，含 "医保智审" 标识

$ curl http://132.232.152.250:5000/api/kp/12005
→ {"id":12005, "name":"ICSI术后", ...}  ← 医疗数据，确认是医保智审 web

$ curl http://132.232.152.250:5000/api/stats
→ 404 ← V1.0 mini-app 接口没部署
```

### 1.4 其他相关服务器

| IP | 用途 | 实测状态 | 备注 |
|---|---|---|---|
| `43.136.175.219` | ~~历史记录~~ | CLOSED | **错误 IP**，从此废弃 |
| `132.232.152.250:2222` | **真实服务器** | OPEN | 唯一活跃服务器 |
| `43.160.242.202` | 历史备份 | 未测 | USER.md 提及，第二台轻量 |
| `43.172.93.38:443` | VLESS Reality 出海代理 | OPEN | **不是服务器**，是 VPN 出口 |
| `127.0.0.1:10808` | 本机 SOCKS5 | 未测 | 本地代理 |

---

## 2. Sir 必须知道的 8 件事

### 2.1 SSH 凭据
```
我这边查不到 MA_SSH_PASS / MA_SSH_USER 环境变量
→ 需要 Sir 给我以下之一：
  (A) SSH 密码（明文，环境变量或当面告诉我）
  (B) SSH 私钥文件路径（推荐，更安全）
  (C) SSH 私钥内容
```

### 2.2 80 端口被占 ⚠️ 关键决策
```
当前 Nginx 在 80 端口跑"中国旅游地图"。
医保智审小程序需要 HTTPS 域名，Nginx 也得配 server_name。
两种方案：

(A) 让医保智审和旅游地图共存（不同 server_name / 不同 listen 端口）
    → api.yibao-zs.cn  → 443 → 反代 :5000（医保智审）
    → travel.yibao-zs.cn → 80 → 现状保留

(B) 把 80 让给医保智审，旅游地图改到别的端口
    → 简单粗暴但影响旅游地图访问

决策：A 还是 B？
```

### 2.3 域名状态
```
api.yibao-zs.cn  未申请（DNS 解析失败）
→ Sir 任务：腾讯云 / 阿里云 注册子域名 + 备案
→ 备案耗时 7-20 天，时间敏感
```

### 2.4 部署路径
```
AGENTS.md 写到 /opt/medical-audit/webapp/
    + gunicorn 服务名 medical-audit.service

推断：
  项目目录：/opt/medical-audit/webapp/
  服务用户：root 或 ubuntu
  Python： 系统 Python 3.10+（gunicorn 默认端口 5000）
  启动：  systemctl 启动 medical-audit.service

待 SSH 连上后确认实际路径
```

### 2.5 数据库位置
```
已知本地: webapp/data/kp.db (~204 MB SQLite)
→ 服务器上路径推断：/opt/medical-audit/webapp/data/kp.db
→ 待确认
```

### 2.6 HTTPS 强制
```
443 没开 → 微信小程序必须 HTTPS
→ 选 Let's Encrypt（最快） 或 腾讯云免费证书
→ OVERVIEW.md §0.2 / DEPLOY.md §1 已有完整配置
```

### 2.7 微信小程序 AppID
```
Sir 还没申请
→ 占位 "touristappid" 在 project.config.json
→ 拿到后改这一行就能用
```

### 2.8 服务器硬件
```
CPU / RAM / 磁盘 / 带宽 未知
→ 推断：腾讯云轻量 2C2G 起步（因为只有 Flask 在跑）
→ 待 SSH 上 uname -a / df -h / free -h / lscpu 确认
```

---

## 3. 我能立刻做的（只要凭据）

```python
# 我用 Paramiko（已装）连服务器：
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    "132.232.152.250", port=2222,
    username=os.environ["MA_SSH_USER"],   # ← Sir 提供
    password=os.environ["MA_SSH_PASS"],   # ← Sir 提供
    timeout=15
)
# 盘点现状：
print(ssh.exec_command("uname -a; df -h; free -h; ls /opt/; cat /etc/nginx/sites-enabled/*"))
```

执行后我会产出一份「服务器现状报告」，含：
- 实际 OS 版本 / 硬件配置
- 当前 systemd 服务清单
- Nginx 配置文件全文
- 项目部署路径 / Python 版本 / 数据库版本
- 端口实际绑定
- 剩余磁盘 / 内存

---

## 4. 我建议的推进顺序

```
Step 1 (今天)    Sir 把 SSH 凭据给我
Step 2 (今天)    我盘点服务器现状 → 出报告
Step 3 (今天)    Sir 决定方案：A(共存) vs B(独占) + 域名选择
Step 4 (1 周内)  Sir 申请 api.yibao-zs.cn + 备案
Step 5 (1 周内)  我部署：Nginx 配置 + 申请 SSL + 重启服务 + 上传新代码
Step 6 (2 周内)  Sir 申请小程序 AppID + 后台配置
Step 7 (2 周)    提审
```

---

## 5. 紧急联系方式 / 应急

```bash
# 服务挂了
ssh -p 2222 ubuntu@132.232.152.250
sudo systemctl status medical-audit
sudo systemctl restart medical-audit
sudo journalctl -u medical-audit -n 100

# Nginx 配置错
sudo nginx -t
sudo nginx -s reload

# 看端口占用
sudo ss -tlnp

# 看磁盘
df -h
du -sh /opt/medical-audit/*
```

---

## 6. 相关文档（项目内）

| 文档 | 路径 | 用途 |
|---|---|---|
| OVERVIEW 总方案 | `miniprogram/OVERVIEW.md` | 7 阶段路线图 + 服务器配置 §0.2 |
| 上线操作手册 | `miniprogram/DEPLOY.md` | step-by-step 部署 |
| V1.x 路线图 | `miniprogram/ROADMAP.md` | V1.0/1.1/1.2/1.3 产品规划 |
| 小程序开发 | `miniprogram/README.md` | 开发说明 |
| 项目部署（旧版） | `deploy_artifacts/DEPLOY.md` | 备份 + 旧 IP 修正说明 |
| 项目 AGENTS.md | `AGENTS.md` | 顶层说明（已是 GBK 乱码） |

---

## 7. 我接下来等你的 3 件事

1. **SSH 凭据**（最关键）→ 我能连上去做实事
2. **端口分配方案**（80 端口归属）→ 我能写最终 Nginx 配置
3. **域名策略**（用 api.yibao-zs.cn 还是别的？） → 我能配 DNS 解析

任一个给我，我都能立刻推进。