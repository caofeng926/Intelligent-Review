# 医保智审规则库 (Intelligent-Review)

国家医保局 (NHSA) 限适应症 / 限性别 / 限儿童等药品 / 耗材审核规则的检索浏览工具,Flask + SQLite 单体 Web 应用,部署在腾讯云 CVM。

> 本文件给 AI 协作用的项目约定,见同目录 `README.md` 了解功能与部署。

## 项目定位

- **形态**:纯 Web 应用,无小程序 / App / CLI 入口
- **数据源**:NHSA 公开政策文件、PDF、XLSX,数据库本地 + 服务器同步
- **数据量**:22,087 知识点 / 32,438 编码 / 81 规则 / 87,499 耗材 / 260,692 药品详情
- **使用者**:医保审核员 / 编码员

## 目录结构

```
.
├── webapp/                  # Flask 主应用
│   ├── app.py              # 入口 + 一级路由
│   ├── db.py               # Schema + 视图 + 连接管理
│   ├── search.py / search_backend.py  # 搜索后端 (FTS5 + jieba)
│   ├── ingest_xlsx.py      # XLSX 批次入库
│   ├── ingest_pdf.py       # PDF 解析入库 (NHSA 公告)
│   ├── ingest_consumables_pdf.py  # 耗材 PDF 入库
│   ├── clean_drug_detail.py # drug_detail.manufacturer 清洗
│   ├── backfill_pinyin.py  # 拼音首字母回填
│   ├── data/kp.db          # SQLite 数据库 (~376 MB, gitignore)
│   ├── templates/          # Jinja2 模板 (16 个页面)
│   └── static/             # 移动端 CSS + JS
├── 01-06批/ 07-15批/ 16批/ 17-...批/ 18-...批/ 19-...批/ 20-...批/  # 历史批次 XLSX/PDF
├── 原始数据/                # NHSA 原始 PDF (~454 MB, gitignore)
├── deploy_artifacts/        # 部署 bundle (rsync 到服务器)
│   ├── webapp/             #   - 仅 runtime 必需 (5 个 .py + templates/ static/ data/)
│   ├── medical-audit.service
│   ├── start.sh
│   └── DEPLOY.md
├── scripts/                 # 同步/部署辅助脚本 (PowerShell + Python)
├── docs/                    # 数据库架构说明
└── README.md
```

## 数据库

**位置**:`webapp/data/kp.db` (SQLite, ~376 MB)
**部署同步**:`/opt/medical-audit/webapp/data/kp.db` (腾讯云 CVM `ubuntu@132.232.152.250:2222`)

### 主要表

| 表 | 行数 | 说明 |
|---|---:|---|
| `batches` | 21 | 批次 (含 NHSA + PDF 2025, 截至第二十批入库后) |
| `rules` | 81 | 审核规则 (36 NHSA + 45 PDF 2025) |
| `knowledge_points` | 22,087 | 知识点 (药品/项目) |
| `knowledge_point_codes` | 32,438 | 医保编码 |
| `consumable_codes` | 87,499 | 耗材代码 + FTS5 索引 |
| `drug_detail` | 260,692 | 药品详情 (含生产厂家) |
| `ivd_codes` / `tcm_codes` / `icd_codes` / `medical_service_codes` / `consumable7_codes` | — | NHSA 6 大类代码表 |
| `kp_fts` / `drug_fts` / `consumable_codes_fts` 等 | — | FTS5 全文索引 |

### drug_detail 字段 (2026-06-28 清洗后)

| 字段 | 说明 |
|---|---|
| `manufacturer` | 清洗后的生产厂家 |
| `manufacturer_raw` | 原始 PDF 解析值 (备份) |
| `manufacturer_flag` | `NULL`=✓ 干净 / `⚠混入规格` / `⚠过短` / `⚠空` / `⚠过长` |

## 部署

- **服务器**:腾讯云 CVM `ubuntu@132.232.152.250:2222` (SSH `ubuntu` / 端口 **2222** / 22 关)
- **服务**:`systemctl restart medical-audit.service`
- **重启需 sudo 喂密码**:`echo "$MA_SSH_PASS" | sudo -S systemctl restart ...` (ubuntu 无 sudoers,凭据走 `$MA_SSH_PASS` 环境变量)
- **远程同步** (Paramiko / scp / rsync):
  ```python
  import paramiko
  ssh = paramiko.SSHClient()
  ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
  ssh.connect("132.232.152.250", port=2222, username="ubuntu",
              password=os.environ["MA_SSH_PASS"], timeout=15)
  sftp = ssh.open_sftp()
  sftp.put("local_path", "/opt/medical-audit/webapp/local_path")
  sftp.close()
  ```

## 常用命令

```bash
# 本地启动 (Python venv)
source .venv/bin/activate
cd webapp && python -m webapp.app
# 浏览器打开 http://127.0.0.1:5000/

# 入库新批次 (XLSX)
cd webapp && python -m webapp.ingest_xlsx

# 入库耗材 PDF
cd webapp && python -m webapp.ingest_consumables_pdf

# 清洗 drug_detail.manufacturer (幂等, 可重复执行)
cd webapp && python -m webapp.clean_drug_detail

# 回填拼音
cd webapp && python -m webapp.backfill_pinyin

# 入库质量检查
cd webapp && python -m webapp.qa

# 数据库查询 (示例)
sqlite3 webapp/data/kp.db "SELECT * FROM knowledge_points LIMIT 10"
```

## 关键约定

1. **PDF 解析边界**:`_strip_footer` 剔除页脚, `spec` 跨多行检测 `\d{6}$` 边界, `generic_no` 不存在时 `spec` 只取首行
2. **FTS5 中文搜索**:`unicode61` 按字分词, 必须用前缀匹配 (如 `"阿泰"*`), 短语匹配返回 0
3. **批次目录命名**:`<NN>批/<NN>-第N批-<主题>/<文件>.xlsx` (容器→批次两层结构)
4. **`manufacturer` 清洗后不能直接编辑**:编辑前先 `manufacturer_raw` 恢复 + 重跑 `clean_drug_detail`
5. **批次 XLSX 文件命名**(防 17 批幂等事故复发):`<NN>第N批"<rule_name>(可选子分类)"规则对应部分知识点明细.xlsx`,**必须用全角弯引号 ""**。`extract_rule_subject` 优先匹配引号内文本(规则名 + 子分类),产生干净的 `rule_subject` 作为 `get_or_create_rule` 的去重键。**禁止**用短横线分隔(如 `第十七批-药品限适应症-抗肿瘤+肌肉骨骼.xlsx`),否则走兜底正则会残留前导分隔符(`-药品限适应症-抗肿瘤+肌肉骨骼`),下次重跑 ingest 时与历史 `rule_subject` 不匹配、产生重复规则 + 重复 KP。12-16 批入库时已遵循弯引号约定,17/18 批已统一改成弯引号风格。
6. **本地 Python 中文路径**(Windows):用 `python -X utf8` 或脚本写到 `$env:TEMP\*.py` 再执行

## 部署 bundle 维护

`deploy_artifacts/webapp/` 是手工维护的精简 bundle,只装 runtime 必需:

- `__init__.py` `app.py` `db.py` `nhsa_api.py` `nhsa_browse.py` `consumables.py`
- `templates/` `static/`
- `data/` (含 kp.db, Server 用)
- `requirements.txt`

**重要**:每次发版前必须从 `webapp/` 拷一份最新代码到 `deploy_artifacts/webapp/`,再 rsync,否则服务器拿的是旧版本。当前 `deploy_artifacts/webapp/` 是 2026-07-30 的快照,**与 `webapp/` 已有差异**。

## 数据导出 (CSV)

位于 `webapp/data/`:

- `export_第一批药品.csv` - 第一批 763 个药品 (基础列)
- `export_第一批药品_完整.csv` - 12 列 (含 KP 信息)
- `export_第一批药品_长表.csv` - 10,870 行 (一个编码一行)
- `export_第一批药品_带厂家.csv` - 14 列 (含厂家+批准文号)
- `export_第一批药品_NHSA风格.csv` - 22 列 (按 NHSA 官方表组织)

## 变更日志 (git history)

- `374b97b` (2026-09-03) - 删除误跟踪的 miniprogram 配置文件
- `f44fca2` (2026-09-03) - **删除所有小程序代码与宣传片, 回归纯网站查询项目**
- `8b4498a` (2026-09-03) - 项目首次纳入 git 版本控制

## AI 协作提示

- 数据库 `kp.db` 不要直接编辑,**只通过 `ingest_*` 入库脚本**。清洗也是用专门的 `clean_drug_detail.py`
- 改动搜索逻辑 (FTS5 / jieba) 前先读 `app.py::jieba_query` 和 `webapp/search.py` 的现有实现
- 新增 API 端点前先看 `nhsa_api.py` 的命名风格 (`/api/nhsa/<table>/<action>`)
- 不要触碰 `原始数据/`,这是 NHSA 原始 PDF,只能读取不能修改
- 不要触碰 `01-06批/` ~ `20-...批/` 的历史文件,只新增下一批次
- 部署相关问题查 `deploy_artifacts/DEPLOY.md` 和 `scripts/sync_to_cvm.ps1`
