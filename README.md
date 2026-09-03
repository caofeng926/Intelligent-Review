# 医保智审规则库 (Intelligent-Review)

> 国家医保局 (NHSA) 发布的限适应症 / 限性别 / 限儿童等药品 / 耗材审核规则的
> 检索浏览工具 —— Flask + SQLite 单体 Web 应用,支持医保编码反查、耗材
> 三级目录浏览、NHSA 20 批次(含 2025 版)规则与 22,087 条知识点。

[![License: 内部使用](https://img.shields.io/badge/license-internal-lightgrey.svg)](#许可)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Flask: 3.x](https://img.shields.io/badge/flask-3.x-orange.svg)](https://flask.palletsprojects.com/)

---

## 目录

1. [功能一览](#功能一览)
2. [技术栈](#技术栈)
3. [目录结构](#目录结构)
4. [数据库](#数据库)
5. [快速上手](#快速上手)
6. [路由与 API](#路由与-api)
7. [数据入库](#数据入库)
8. [部署](#部署)
9. [常见问题](#常见问题)
10. [变更日志](#变更日志)
11. [许可](#许可)

---

## 功能一览

- **关键词搜索**(中文 `unicode61` 前缀 FTS5 + 拼音首字母 / 医保编码反查)
- **医保编码 / 耗材 C-code 反查**(15 位医保编码、20 位耗材代码)
- **三级耗材目录浏览**(`L1 → L2 → L3 → C-code`)
- **NHSA 批次分组浏览**(yp 药品 / hc7 耗材 / tcm 中药饮片 / icd 诊断 / ms 手术 / ivd 体外诊断)
- **审核规则详情**(限适应症、配对项目、配对手术等结构化展开)
- **首页统计** + 最近更新 + 编码示例
- **JSON API** 供外部脚本消费(`/api/*` 路由)

## 技术栈

| 层 | 选择 |
|---|---|
| Web | Flask 3.x + Jinja2 |
| WSGI | gunicorn (生产) / Flask dev server (本地) |
| DB | SQLite 3.45+ (FTS5 全文检索) |
| 分词 | unicode61 (中文按字) |
| 入库 | openpyxl (XLSX) · pdfplumber + PyMuPDF (PDF) |
| 拼音 | pypinyin (用于首字母补全) |
| 服务器 | Linux (Ubuntu 22.04+) · gunicorn · systemd |
| 反向代理 | 直绑 `0.0.0.0:5000` 或经 Nginx |

## 目录结构

```
.
├─ webapp/                         # 主应用
│  ├─ app.py                       # 入口 + 一级路由 (~420 行)
│  ├─ nhsa_api.py                  # NHSA 数据 JSON API
│  ├─ nhsa_browse.py               # NHSA 静态浏览页
│  ├─ db.py                        # Schema + 视图 + 连接管理 (~630 行)
│  ├─ search.py / search_backend.py# 搜索后端 (FTS5 + jieba 候选)
│  ├─ ingest_*.py                  # XLSX/PDF/CSV 入库 (10 个)
│  ├─ clean_drug_detail.py         # drug_detail.manufacturer 清洗
│  ├─ backfill_pinyin.py           # 拼音首字母回填
│  ├─ qa.py                        # 入库质量检查
│  ├─ admin.py                     # 后台管理 Blueprint
│  ├─ consumables.py               # 耗材 API
│  ├─ templates/                   # Jinja2 模板 (16 个页面)
│  ├─ static/                      # 移动端 CSS + JS
│  └─ data/                        # SQLite + 导出 CSV + 完整性报告
├─ 01-06批/ 07-15批/ 16批/ 17批/.../20批/   # 历史批次 XLSX/PDF
├─ 原始数据/                         # NHSA 原始 PDF (~454 MB)
├─ deploy_artifacts/               # 部署 bundle (rsync 到服务器用)
│  ├─ webapp/                      #   - 仅含运行时所需文件
│  ├─ medical-audit.service        #   - systemd 单元
│  ├─ start.sh                     #   - 启动脚本
│  └─ DEPLOY.md                    #   - 部署指引
├─ scripts/                        # 同步/部署辅助脚本 (PowerShell + Python)
├─ docs/                           # 数据库架构说明
├─ AGENTS.md                       # 项目内 AI 协作约定
├─ README.md                       # 本文件
└─ .gitignore
```

## 数据库

**位置**:`webapp/data/kp.db`(本地,约 376 MB)
**部署**:`/opt/medical-audit/webapp/data/kp.db`(腾讯云 CVM,VACUUM 后更紧凑)

### 主要表 (截至 2026-09-03)

| 表 | 行数 | 说明 |
|---|---:|---|
| `batches` | 21 | 批次 (含 NHSA + PDF 2025, 截至第二十批入库后) |
| `rules` | 81 | 审核规则 (36 NHSA + 45 PDF 2025) |
| `knowledge_points` | 22,087 | 知识点 (药品 / 项目) |
| `knowledge_point_codes` | 32,438 | 知识点 ↔ 医保编码 (多对一) |
| `consumable_codes` | 87,499 | 耗材代码 + FTS5 索引 |
| `drug_detail` | 260,692 | 药品详情 (含清洗后的生产厂家) |
| `ivd_codes` / `tcm_codes` / `icd_codes` / `medical_service_codes` / `consumable7_codes` | 79k / 3.4k / 33k / 8.2k / — | NHSA 6 大类代码表 |
| `kp_fts` / `drug_fts` / `consumable_codes_fts` / `ivd_codes_fts` 等 | — | FTS5 全文索引 |

### drug_detail 字段 (2026-06-28 清洗后)

| 字段 | 说明 |
|---|---|
| `manufacturer` | 清洗后的生产厂家 |
| `manufacturer_raw` | 原始 PDF 解析值 (备份) |
| `manufacturer_flag` | `NULL`=✓ 干净 / `⚠混入规格` / `⚠过短` / `⚠空` / `⚠过长` |

### 视图

- `consumable_categories` —— 一级分类聚合 (供 `/api/consumable-categories`)

## 快速上手

### 依赖

- Python 3.10+
- 推荐 `git clone` + `.venv`

```bash
# 1. 克隆
git clone https://github.com/caofeng926/Intelligent-Review.git
cd Intelligent-Review

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate           # bash / zsh
# 或 .venv\Scripts\Activate.ps1   # PowerShell

# 3. 安装运行时依赖
pip install "flask>=3.0" "gunicorn>=22.0" "jieba>=0.42"

# 3'. 安装完整依赖 (含入库工具)
pip install -r webapp/requirements.txt   # 若存在

# 4. 启动
cd webapp && python -m webapp.app

# 5. 访问
# 浏览器打开 http://127.0.0.1:5000/
```

## 路由与 API

### 路由 (HTML)

| 路径 | 说明 |
|---|---|
| `/` | 首页 + 统计 + 最近更新 + 编码示例 |
| `/search?q=&page=&mode=&source=` | 关键词搜索结果页 |
| `/search/{yp,hc,tcm,icd,ivd,ms}` | 五大分类搜索 |
| `/rules` | 按批次浏览规则 |
| `/rules/<rid>` | 单条规则的知识点列表 |
| `/kp/<kp_id>` | 单条 KP 详情 |
| `/consumables` `/consumables/cat/<l1>` `/consumables/cat/<l1>/<l2>` | 耗材 1/2 级目录 |
| `/consumables/cat/<l1>/<l2>/<l3>` | 耗材 3 级目录 + C-code 表 (200 条样例) |
| `/consumables/code/<code>` | 单条耗材详情 |
| `/nhsa` 及 `/nhsa/{yp,hc7,tcm,icd,ms,ivd}` | NHSA 静态浏览页 |
| `/nhsa/{yp,hc7,tcm,icd,ms,ivd}/code/<code>` | NHSA 编码反查 |
| `/admin/...` | 后台管理 (无默认 UI, 需配 BasicAuth) |

### JSON API

| 路径 | 说明 |
|---|---|
| `GET /api/stats` | 全表行数统计 |
| `GET /api/recent?limit=12` | 最近更新的 KP 列表 |
| `GET /api/search?q=&mode={auto,name,initials,code}&page=` | 通用搜索 (审核规则) |
| `GET /api/code/<code>` | 医保编码反查 (匹配任意代码表) |
| `GET /api/consumable/<code>` | 单条耗材 JSON |
| `GET /api/consumable-categories` | 耗材一级分类聚合 |
| `GET /api/rule-categories` | 按类型分组的规则 |
| `GET /api/nhsa/stats` | NHSA 全部批次元数据 |
| `GET /api/nhsa/batches` | 批次清单 |
| `GET /api/nhsa/yp/{search,code/<c>,approval/<no>}` | NHSA 药品 |
| `GET /api/nhsa/hc/search` | NHSA 耗材 (FTS5 + LIKE 兜底) |
| `GET /api/nhsa/hc7/code/<code>` | NHSA 7 类耗材 |
| `GET /api/nhsa/icd/{search,code/<c>}` | NHSA ICD-10 |
| `GET /api/nhsa/ivd/{search,code/<c>}` | NHSA 体外诊断 |
| `GET /api/nhsa/ms/{search,code/<c>}` | NHSA 医疗服务 |
| `GET /api/nhsa/tcm/{search,code/<c>}` | NHSA 中药饮片 |

## 数据入库

```bash
cd webapp

# 1. XLSX 批次入库 (NHSA 公告附件)
python -m webapp.ingest_xlsx

# 2. PDF 解析入库 (NHSA 公告 PDF)
python -m webapp.ingest_pdf

# 3. 耗材 PDF 入库
python -m webapp.ingest_consumables_pdf

# 4. NHSA 数据库快照入库
python -m webapp.ingest_nhsa_dbs

# 5. 清洗 drug_detail.manufacturer (幂等,可重跑)
python -m webapp.clean_drug_detail

# 6. 拼音首字母回填
python -m webapp.backfill_pinyin

# 7. 入库质量检查
python -m webapp.qa
```

**重要约束**:

- `clean_drug_detail.py` 后,`manufacturer` 不能直接编辑 —— 先用 `manufacturer_raw` 还原再重跑。
- `*.db` 和 `原始数据/` 已 `.gitignore`,**不会**进 git。

## 部署

### 目标服务器

- 腾讯云 CVM `ubuntu@132.232.152.250:2222` (SSH `ubuntu` / 端口 **2222** / 22 关)
- 工作目录 `/opt/medical-audit`(包含 `.venv/`、`webapp/`)
- 服务单元 `/etc/systemd/system/medical-audit.service`
- 重启 systemctl 需 `echo "$MA_SSH_PASS" | sudo -S` 喂密码 (ubuntu 无 sudoers,凭据走环境变量)

### systemd 单元

```ini
[Unit]
Description=Medical Audit Webapp
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/medical-audit
ExecStart=/opt/medical-audit/.venv/bin/gunicorn \
    --bind 0.0.0.0:5000 --workers 2 --threads 2 --timeout 60 \
    --access-logfile - --error-logfile - \
    webapp.app:app
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### 部署步骤 (rsync)

```bash
# 1. 上线新代码 (本地 → 服务器)
rsync -av --delete \
  --exclude='data/kp.db' --exclude='__pycache__/' --exclude='*.pyc' \
  -e "ssh -p 2222" \
  deploy_artifacts/webapp/ \
  ubuntu@132.232.152.250:/opt/medical-audit/webapp/

# 2. 重启
ssh -p 2222 ubuntu@132.232.152.250 \
  'echo "$MA_SSH_PASS" | sudo -S systemctl restart medical-audit.service'

# 3. 验证
curl -o /dev/null -w "%{http_code}\n" http://132.232.152.250:5000/
```

### 数据库同步策略

- **本地**:`webapp/data/kp.db`(~376 MB,源数据)
- **服务器**:`/opt/medical-audit/webapp/data/kp.db`(生产库,VACUUM 后更紧凑)
- **不要混传** —— 两库行数 / 日期范围 / id 范围应全等
- 入库在本机测试,稳定后单独同步 kp.db 到服务器

## 常见问题

**Q: FTS5 中文搜索为什么用前缀匹配 (`阿泰*`)?**
A: SQLite 自带的 `unicode61` 分词器把每个汉字当一个 token,短语查询 (`"阿泰特韦"`) 永远返回 0 行。改用 `q[:2]*` 前缀匹配解决。

**Q: 服务挂了 (`ModuleNotFoundError: No module named 'webapp.app'`) 怎么办?**
A: 通常是 `webapp/` 目录为空或被覆盖。检查:
1. `ls /opt/medical-audit/webapp/` 应包含 `app.py` `db.py` `templates/` 等
2. 用 `systemctl restart` 重启
3. `journalctl -u medical-audit -n 50` 看 trace

**Q: 改完模板不生效?**
A: gunicorn 重启会清缓存,`systemctl restart medical-audit.service` 即可。

**Q: 部署包 (`deploy_artifacts/webapp/`) 怎么更新?**
A: 这是手工维护的部署 bundle,只装 runtime 必需文件 (`__init__.py` `app.py` `db.py` `nhsa_api.py` `nhsa_browse.py` `templates/` `static/` `data/` `requirements.txt`)。每次发版前从 `webapp/` 拷一份最新代码过去,再用 rsync。

## 变更日志

### `374b97b` (2026-09-03)
- chore: 删除被初次 commit 误跟踪的 `miniprogram/project.private.config.json`
- 项目精简: 移除所有微信小程序相关代码、宣传片素材、调试脚本、调试截图

### `f44fca2` (2026-09-03)
- chore: 删除小程序相关代码与宣传片, 回归纯网站查询项目
- 删除 `miniprogram/` `hf-promo/` `project.config.json`
- 移除 8 个小程序 API 端点 + 鉴权 helper + MINIAPP_SCHEMA (6 张表)

### `8b4498a` (2026-09-03)
- init: 项目首次纳入 git 版本控制
- 含 22 万条医保数据 + Flask 后端 + 18 批次 PDF/XLSX 源文件

## 许可

仅供内部使用。数据归 NHSA 所有。
