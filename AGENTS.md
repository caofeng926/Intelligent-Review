# 医保智审规则库 (Medical Audit Rules Library)

医保智能审核规则库 — NHSA 发布的限适应症 / 限性别 / 限儿童等药品审核规则，含 PDF/XLSX 解析入库、医保编码/耗材代码库、Web 检索。

## 目录结构

```
.
├── webapp/                  # 主应用 (Flask + SQLite)
│   ├── app.py              # 路由 / API
│   ├── db.py               # Schema + 视图
│   ├── search.py           # 搜索逻辑 (FTS5 + jieba)
│   ├── ingest_xlsx.py      # XLSX 批次入库
│   ├── ingest_pdf.py       # PDF 解析入库
│   ├── ingest_consumables_pdf.py  # 耗材 PDF 入库
│   ├── clean_drug_detail.py # drug_detail.manufacturer 清洗
│   ├── backfill_pinyin.py  # 拼音首字母回填
│   ├── data/kp.db          # SQLite 数据库 (~204 MB)
│   ├── templates/          # Jinja2 模板
│   └── static/             # CSS / JS
├── 01-06批/                 # 早期批次 XLSX/PDF
├── 07-15批/                # 中期批次
├── 16批/                   # 最新批次 (第十六批)
├── 原始数据/                # NHSA 原始 PDF
├── _start.ps1              # 本地启动 (PowerShell)
└── 医疗保障基金智能监管规则库、知识库（2025年版）.pdf  # 2025 PDF 源
```

## 数据库

**位置**：`webapp/data/kp.db` (SQLite, 204 MB)
**部署同步**：`/opt/medical-audit/webapp/data/kp.db` (腾讯云 CVM `43.136.175.219:5000`)

### 主要表

| 表 | 数量 | 说明 |
|---|---|---|
| `batches` | 17 | 批次 (含 NHSA + PDF 2025) |
| `rules` | 77 | 审核规则 (32 NHSA + 45 PDF 2025) |
| `knowledge_points` | 21,658 | 知识点 (药品/项目) |
| `knowledge_point_codes` | 28,929 | 医保编码 |
| `consumable_codes` | 89,279 | 耗材代码 + FTS5 索引 |
| `drug_detail` | 187,426 | 药品详情 (含生产厂家) |
| `kp_fts` / `drug_fts` / `consumable_codes_fts` | — | FTS5 全文索引 |

### drug_detail 字段 (2026-06-28 清洗后)

| 字段 | 说明 |
|---|---|
| `manufacturer` | 清洗后的生产厂家 |
| `manufacturer_raw` | 原始 PDF 解析值 (备份) |
| `manufacturer_flag` | `NULL`=✓干净 / `⚠混入规格` / `⚠过短` / `⚠空` / `⚠过长` |

## 部署

- **服务器**：腾讯云 CVM `43.136.175.219:5000` (SSH `root / 2Vbrm5ah`)
- **服务**：`systemctl restart medical-audit.service`
- **远程同步** (Paramiko / scp)：
  ```python
  import paramiko
  ssh = paramiko.SSHClient()
  ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
  ssh.connect("43.136.175.219", port=22, username="root", password="2Vbrm5ah", timeout=15)
  sftp = ssh.open_sftp()
  sftp.put("local_path", "/opt/medical-audit/webapp/local_path")
  sftp.close()
  ```

## 常用命令

```bash
# 本地启动
.\u005f_start.ps1

# 入库新批次 (XLSX)
cd webapp && python -m webapp.ingest_xlsx

# 入库耗材 PDF
cd webapp && python -m webapp.ingest_consumables_pdf

# 清洗 drug_detail.manufacturer (幂等, 可重复执行)
cd webapp && python -m webapp.clean_drug_detail

# 回填拼音
cd webapp && python -m webapp.backfill_pinyin

# 数据库导出 (示例)
sqlite3 webapp/data/kp.db "SELECT * FROM knowledge_points LIMIT 10"
```

## 关键约定

1. **PDF 解析边界**：`_strip_footer` 剔除页脚, `spec` 跨多行检测 `\d{6}$` 边界, `generic_no` 不存在时 `spec` 只取首行
2. **FTS5 中文搜索**：`unicode61` 按字分词, 必须用前缀匹配 (如 `"阿泰"*`), 短语匹配返回 0
3. **PowerShell 中文路径**：用 `python -X utf8` 或脚本写到 `$env:TEMP\*.py` 再执行
4. **批次目录命名**：`<NN>批/<NN>-第N批-<主题>/<文件>.xlsx` (容器→批次两层结构)
5. **`manufacturer` 清洗后不能直接编辑**：编辑前先 `manufacturer_raw` 恢复 + 重跑 `clean_drug_detail`

## 数据导出 (CSV)

位于 `webapp/data/`：
- `export_第一批药品.csv` - 第一批 763 个药品 (基础列)
- `export_第一批药品_完整.csv` - 12 列 (含 KP 信息)
- `export_第一批药品_长表.csv` - 10,870 行 (一个编码一行)
- `export_第一批药品_带厂家.csv` - 14 列 (含厂家+批准文号)
- `export_第一批药品_NHSA风格.csv` - 22 列 (按 NHSA 官方表组织)
