# 医保智审规则库 (Intelligent-Review)

> 国家医保局 (NHSA) 发布的限适应症 / 限性别 / 限儿童等药品 / 耗材审核规则的
> 检索浏览工具 —— Flask + SQLite,支持医保编码反查、耗材三级目录浏览、
> NHSA 17 批次(含 2025 版)规则与 21,658 条知识点。

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
9. [本地 ↔ GitHub ↔ 服务器三向同步](#本地--github--服务器三向同步)
10. [常见问题](#常见问题)
11. [许可](#许可)

---

## 功能一览

- **关键词搜索**(中文 `unicode61` 前缀 FTS5 + 拼音首字母)
- **医保编码 / 耗材 C-code 反查**(15 位医保编码、20 位耗材代码)
- **三级耗材目录浏览**(`L1 → L2 → L3 → C-code`)
- **NHSA 批次分组浏览**(yp 药品 / hc7 耗材 / tcm 中药饮片 / icd 诊断 / ms 手术 / ivd 体外诊断)
- **审核规则详情**(限适应症、配对项目、配对手术等结构化展开)
- **首页统计** + 最近更新 + 编码示例
- **JSON API** 供外部小程序 / 数据脚本消费

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
│  ├─ app.py                       # 入口 + 一级路由
│  ├─ nhsa_api.py                  # NHSA 数据 API (/api/nhsa/*)
│  ├─ nhsa_browse.py               # NHSA 静态路由 (/nhsa/*)
│  ├─ db.py                        # Schema + 视图 + 连接管理
│  ├─ search.py                    # 搜索后端 (FTS5 + jieba 候选)
│  ├─ ingest_xlsx.py               # 批量 XLSX 入库
│  ├─ ingest_pdf.py                # PDF 解析入库 (NHSA 公告)
│  ├─ ingest_consumables_pdf.py    # 耗材 PDF 入库
│  ├─ ingest_nhsa_dbs.py           # NHSA 数据库快照入库
│  ├─ clean_drug_detail.py         # drug_detail.manufacturer 清洗
│  ├─ backfill_pinyin.py           # 拼音首字母回填
│  ├─ qa.py                        # 入库质量检查
│  ├─ templates/                   # Jinja2 模板 (16 个页面)
│  ├─ static/                      # 移动端 CSS + JS
│  └─ data/                        # SQLite + 导出 CSV + 完整性报告
├─ docs/                           # 数据库架构说明
├─ hf-promo/                       # HyperFrames 宣传视频材料
├─ AGENTS.md                       # 项目内 AI 协作约定
├─ README.md                       # 本文件
└─ .gitignore                      # 排除大文件、调试脚本、__pycache__
```

## 数据库

**位置**:`webapp/data/kp.db`(本地,约 434 MB)
**部署**:`/opt/medical-audit/webapp/data/kp.db`(腾讯云 CVM,约 368 MB,VACUUM 后)
**部署同步**:Paramiko SCP 或 `rsync` 增量

### 主要表 (截至 2026-06)

| 表 | 行数 | 说明 |
|---|---:|---|
| `batches` | 17 | 批次 (含 NHSA 32 条 + 2025 PDF 45 条) |
| `rules` | 77 | 审核规则 |
| `knowledge_points` | 21,658 | 知识点 (药品 / 项目) |
| `knowledge_point_codes` | 29,872 | 知识点 ↔ 医保编码 (多对一) |
| `consumable_codes` | 89,279 | 耗材代码 + FTS5 索引 |
| `drug_detail` | 260,692 | 药品详情 (含清洗后的生产厂家) |
| `kp_fts` / `consumable_codes_fts` | — | FTS5 全文索引 |

### drug_detail 字段 (2026-06-28 清洗后)

| 字段 | 说明 |
|---|---|
| `manufacturer` | 清洗后的生产厂家 |
| `manufacturer_raw` | 原始 PDF 解析值(备份) |
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
.venv\Scripts\Activate.ps1   # PowerShell
# 或 source .venv/bin/activate  # bash

# 3. 安装运行时依赖 (服务端只装这三个足够)
pip install "flask>=3.0" "gunicorn>=22.0" "jieba>=0.42"

# 3'. 安装完整依赖 (含入库工具)
pip install -r webapp/requirements.txt

# 4. 启动
.\\_start.ps1
# 或:
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

### JSON API

| 路径 | 说明 |
|---|---|
| `/api/search?q=&mode={auto,name,initials,code}` | 通用搜索 |
| `/api/kp/<kp_id>` | 单条 KP 详情 JSON |
| `/api/code/<code>` | 医保编码反查 |
| `/api/consumable/<code>` | 单条耗材 JSON |
| `/api/consumable-categories` | 耗材一级分类聚合 |
| `/api/rule-categories` | 按类型分组的规则 |
| `/api/nhsa/stats` | NHSA 全部批次元数据 |
| `/api/nhsa/batches` | 批次清单 |
| `/api/nhsa/yp/{search,code/<c>,approval/<no>}` | NHSA 药品接口 |
| `/api/nhsa/hc7/code/<code>` | NHSA 耗材 |
| `/api/nhsa/icd/{search,code/<c>}` | NHSA 诊断 |
| `/api/nhsa/ivd/{search,code/<c>}` | NHSA 体外诊断 |
| `/api/nhsa/ms/{search,code/<c>}` | NHSA 手术 |
| `/api/nhsa/tcm/{search,code/<c>}` | NHSA 中药饮片 |

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

### 方案 A:腾讯云 CVM 直跑 (本项目采用)

**目标服务器**:`43.136.175.219:5000` (Ubuntu 22.04+)
**服务单元**:`/etc/systemd/system/medical-audit.service`
**工作目录**:`/opt/medical-audit`(包含 `.venv/`、`webapp/`,git 仅 webapp/ 内容被管理)

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

部署:

```bash
# 上线新代码 (本地)
rsync -av --delete \
  --exclude='data/kp.db' --exclude='__pycache__/' --exclude='*.pyc' \
  -e "ssh -p 22" \
  ./webapp/ root@43.136.175.219:/opt/medical-audit/webapp/

# 重启
ssh root@43.136.175.219 'systemctl restart medical-audit.service'

# 验证
curl -o /dev/null -w "%{http_code}\n" http://43.136.175.219:5000/
```

### 数据库策略

- **本地**:`webapp/data/kp.db` (~434 MB,未 VACUUM)
- **服务器**:`/opt/medical-audit/webapp/data/kp.db` (~368 MB,VACUUM 后更紧凑)
- **不要混传** —— 两库内容完全一致,行数 / 日期范围 / id 范围全等,只是文件大小因 VACUUM 不同
- 服务器库是生产库,在做入库时本地跑测试 / 服务器跑生产
- 入库后在本机 `python -m webapp.qa` 跑质量校验

## 本地 ↔ GitHub ↔ 服务器三向同步

```
  ┌─────────────┐  git push  ┌───────────────┐  sftp/rsync  ┌────────────────┐
  │   本机 repo │ ─────────►│  GitHub main  │ ───────────► │  服务器 webapp/ │
  │  (本地开发) │ ◄─────────│  caofeng926/  │ ◄─── git pull│ (生产 gunicorn) │
  └─────────────┘   git pull └───────────────┘   ──────────  └────────────────┘
                                                          (server pulls from
                                                           github or local sftp)
```

1. 本机 commit 后 `git push origin main`
2. 触发 GitHub Actions / webhook → 服务器 `git pull && systemctl restart`
3. 或本机 `rsync` 直推,然后 `systemctl restart`

⚠️ 服务器上 `.venv` 与 `data/*.db` 被 git 忽略,需要单独同步:
- `.venv` 在新机第一次 `pip install -r webapp/requirements.txt` 即可重建
- `data/*.db` 见上文"数据库策略"

## 常见问题

**Q: FTS5 中文搜索为什么用前缀匹配 (`阿泰*`)?**
A: SQLite 自带的 `unicode61` 分词器把每个汉字当一个 token,短语查询 (`"阿泰特韦"`) 永远返回 0 行。改用 `q[:2]*` 前缀匹配解决。详见 `app.py::jieba_query`。

**Q: `?l3=` 这种空查询参数是什么?**
A: 旧版 `consumables.html` 用 `url_for(..., l3=g.l3)` 生成链接,即便 `g.l3=None` 也会拼成查询。已在 `b55ea8c` 修复。

**Q: 服务挂了 (`ModuleNotFoundError: No module named 'webapp.app'`) 怎么办?**
A: 通常是 `webapp/` 目录为空或被覆盖。检查:
1. `ls /opt/medical-audit/webapp/` 应包含 `app.py` `db.py` `templates/` 等
2. 用 `systemctl restart` 重启
3. `journalctl -u medical-audit -n 50` 看 trace

**Q: 改完模板不生效?**
A: gunicorn 重启会清缓存,`systemctl restart medical-audit.service` 即可。

## 变更日志

### `b55ea8c` (2026-06-29)
- 修复 `/consumables/cat/01/?l3=...` 404
- 全部 `/consumables*` 路由加 `strict_slashes=False`
- 新增 `/consumables/cat/<l1>/<l2>/<l3>` 三级目录详情页 (前 200 条 C-code)
- 模板 `consumables.html` 不再生成 `?l3=` 空查询
- `.gitignore` 排除 `webapp/data/_pdf_yp_chunks/`

### `f5a1c1c` (2026-06-29)
- 远端 init 与本地项目合并 (含 1 个占位 `README.md`)

### `5e0585a` (2026-06-29)
- 本地初始 commit:`webapp/` 应用 + 文档 + HyperFrames 宣传视频材料

## 许可

仅供内部使用。数据归 NHSA 所有。
