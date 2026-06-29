# 医保智审规则库 · 数据库结构文档


> 自动生成于 **2026-06-29 09:30** · 数据库 `webapp/data/kp.db` (414.4 MB)

本文档描述 SQLite 数据库的表结构、字段含义、索引和 FTS5 全文索引配置。

## 1. 数据库概况

| 表名 | 行数 | 用途 |
|---|---:|---|
| `batches` | 17 | 审核规则批次（NHSA 公告 + PDF 合并版） |
| `rules` | 77 | 审核规则主体（含 object_type 分类） |
| `knowledge_points` | 21,658 | 审核知识点（KP，规则的具体条目） |
| `knowledge_point_codes` | 29,872 | KP ↔ 医保编码 多对多映射 |
| `drug_detail` | 260,692 | 药品详细信息（厂家、批准文号、规格） |
| `yp_codes` | 260,692 | 医保药品代码主表（与 `drug_detail` 镜像） |
| `consumable_codes` | 89,279 | 医保医用耗材代码 |
| `consumable7_codes` | 3,728 | 7 大类医用耗材精简版 |
| `tcm_codes` | 1,369 | 中医病证术语与代码（GB/T 15657） |
| `icd_codes` | 33,304 | ICD-10 国标版医保疾病诊断代码 |
| `ivd_codes` | 79,009 | 医保体外诊断试剂代码 |
| `medical_service_codes` | 8,220 | 医保医疗服务项目代码（15 位） |
| `nhsa_batches` | 8 | NHSA 抓取批次元数据 |

### 1.1 逻辑分层

```
┌─────────────────────────────────────────────────────┐
│  规则层  batches ──< rules ──< knowledge_points    │
│                  (1:N)         (1:N)                │
│                                       │              │
│                                       ├── kpc ──┐   │
│                                       │ (1:N)   │   │
│  代码层                                     ▼     │
│  yp_codes / drug_detail / consumable_codes / ...   │
│  (通过 knowledge_point_codes.code 关联)            │
└─────────────────────────────────────────────────────┘
```

## 2. 规则层表

### 2.1 `batches` 批次元数据

| 字段 | 类型 | 必填 | 说明 |
|---|---|:-:|---|
| `id` | INTEGER PK | ✓ | 自增主键 |
| `source` | TEXT | ✓ | 数据源：`nhsa_batch` / `pdf_2025` |
| `batch_label` | TEXT | ✓ | 批次显示名（'第一批'…'第十六批'、'2025版合并版(自PDF)'） |
| `rule_subject` | TEXT |   | 规则主题（与 rules 表的 subject 共享；用 IFNULL 兼容） |
| `pub_date` | TEXT |   | 公告发布日期 (YYYY-MM-DD) |
| `ann_url` | TEXT |   | NHSA 公告原文 URL |
| `pdf_path` | TEXT |   | 本地 PDF 源文件路径 |
| `xlsx_path` | TEXT |   | 本地 XLSX 结构化文件路径 |

**唯一索引** `idx_batches_uniq` ON `(source, batch_label, IFNULL(rule_subject,''))` — 同一来源+标签+主题只能入库一次。

### 2.2 `rules` 审核规则

| 字段 | 类型 | 必填 | 说明 |
|---|---|:-:|---|
| `id` | INTEGER PK | ✓ | 自增主键 |
| `batch_id` | INTEGER FK | ✓ | 所属批次 → `batches.id` (CASCADE) |
| `source` | TEXT | ✓ | 数据源（冗余，便于 JOIN-less 过滤） |
| `rule_subject` | TEXT | ✓ | 规则主题（如 '药品区分性别使用'） |
| `category` | TEXT |   | 业务大类（医疗-药品 / 医疗-项目 / 中医-饮片 …） |
| `object_type` | TEXT |   | 知识对象类型：`drug` / `tcm` / `tcm_decoction` / `consumable` / `service` / `pair` |
| `page_start` | INTEGER |   | PDF 起始页（用于回查） |
| `page_end` | INTEGER |   | PDF 结束页 |
| `xlsx_path` | TEXT |   | 来源 XLSX 路径 |
| `row_count` | INTEGER |   | 该规则下的 KP 行数 |

**唯一索引** `uniq_rules_batch_subject` ON `(source, batch_id, rule_subject)`
**索引** `idx_rules_source` / `idx_rules_subject` / `idx_rules_cat`

#### `rules.object_type` 取值分布

| object_type | rules 数量 | KP 数量 | 含义 |
|---|---:|---:|---|
| `drug` | 46 | 9,004 | 西药/中成药审核条目 |

### 2.3 `knowledge_points` 知识点（KP）

| 字段 | 类型 | 必填 | 说明 |
|---|---|:-:|---|
| `id` | INTEGER PK | ✓ | 自增主键 |
| `rule_id` | INTEGER FK | ✓ | 所属规则 → `rules.id` (CASCADE) |
| `seq` | INTEGER |   | 在规则内的序号 |
| `subject_name` | TEXT |   | KP 名称（药品名/项目名/诊断名） |
| `code_count` | INTEGER |   | 该 KP 名义上关联的编码数（声明值，可能与 `codes` 长度不同） |
| `detection_logic` | TEXT |   | 检出逻辑描述（人类可读） |
| `logic_basis` | TEXT |   | 逻辑依据（法规/指南引用） |
| `codes` | TEXT |   | 关联的医保编码文本（多码用 `・` U+30FB 分隔） |
| `remark` | TEXT |   | 备注 |
| `raw_row` | TEXT |   | 原始 PDF 行 JSON（用于回查与 partner 解析） |
| `pinyin_initials` | TEXT |   | 名称的拼音首字母（搜索用） |

**索引** `idx_kp_rule` / `idx_kp_seq` / `idx_kp_pinyin`

#### `raw_row` JSON 格式约定

- `pair` 类型：`{seq, subject_name, codes, subject_name_b, codes_b, detection_logic, logic_basis, remark}` — B 端编码直接可用
- `service` 类型：`{page, row: [seq, surgery_code, surgery_name, ?, dx_code, dx_name, detection_logic, basis]}` — 手术码在 `row[1]`
- `tcm_decoction` 类型：`{page, row: [seq, name, T_code, ...]}`
- `consumable` 类型：`{page, row: [seq, name, detection_logic, basis, remark, count]}` — 无国家码
- `drug` 类型：`{seq, subject_name, remark, detection_logic, logic_basis, code_count}` — codes 多在 XLSX 中，PDF 解析时往往缺

### 2.4 `knowledge_point_codes` KP ↔ 编码 多对多

| 字段 | 类型 | 必填 | 说明 |
|---|---|:-:|---|
| `kp_id` | INTEGER FK | ✓ | → `knowledge_points.id` (CASCADE) |
| `code_seq` | INTEGER | ✓ | 同 KP 多码时排序（1 起） |
| `code` | TEXT | ✓ | 医保编码（yp 20/23 位、service 15 位、consumable 19-21 位、tcm_decoction 10 位 T-码） |

**唯一索引** `uniq_kpc` ON `(kp_id, code)`
**索引** `idx_kpc_kp` / `idx_kpc_code`

#### KP × codes 关系总览

| object_type | KP 数 | 有 kpc 的 KP | 唯一 code 数 |
|---|---:|---:|---:|
| `drug` | 9,004 | 2,146 | 18,147 |
| `pair` | 900 | 900 | 528 |
| `service` | 9,060 | 1,036 | 846 |
| `tcm` | 153 | 153 | 153 |
| `tcm_decoction` | 1,834 | 0 | 0 |
| `consumable` | 707 | 0 | 0 |

## 3. 代码层表

### 3.1 `drug_detail` / `yp_codes` 药品信息

两份表镜像存储（行数都是 260,692），`yp_codes` 是精简版（16 列），`drug_detail` 增加审计字段。

#### `drug_detail`

| 字段 | 类型 | 填充率 | 说明 |
|---|---|---:|---|
| `goods_code` | TEXT PK | 100% | 医保药品代码（20/23 位），主键 |
| `reg_name` | TEXT | 100% | 注册名称（中文） |
| `reg_dosage_form` | TEXT | 100% | 注册剂型 |
| `reg_spec` | TEXT | 100% | 注册规格 |
| `product_name` | TEXT | 100% | 商品名称 |
| `dosage_form` | TEXT | 100% | 剂型 |
| `spec` | TEXT | 100% | 规格 |
| `packaging` | TEXT | 100% | 包装材质 |
| `min_pkg_qty` | TEXT | 100% | 最小包装数量 |
| `min_prep_unit` | TEXT | 100% | 最小制剂单位 |
| `min_pkg_unit` | TEXT | 100% | 最小包装单位 |
| `manufacturer` | TEXT | 100% | 药品企业（清洗后） |
| `approval_no` | TEXT | 100% | 批准文号（如 国药准字 H20050001） |
| `base_code` | TEXT | 100% | 药品本位码（8690…） |
| `list_class` | TEXT | 65.2% | 国家医保目录 甲/乙类 |
| `list_no` | TEXT | 65.2% | 目录编号 |
| `list_drug_name` | TEXT | 65.2% | 目录药品名称 |
| `list_dosage_form` | TEXT | 42.7% | 目录剂型 |
| `list_remark` | TEXT | 4.1% | 目录备注（限适应症等） |
| `source_pdf` | TEXT | 100% | 来源 PDF 文件名 |
| `version_date` | TEXT | 100% | 数据时点（YYYY-MM-DD） |
| `first_seen_page` | INTEGER | — | 首次出现页码（审计字段） |
| `row_count` | INTEGER | — | 重复行计数（默认 1） |
| `manufacturer_flag` | TEXT | — | 清洗标记：NULL=✓ / ⚠混入规格 / ⚠过短 / ⚠空 / ⚠过长 |
| `manufacturer_raw` | TEXT | — | 原始 manufacturer（清洗前备份） |

**索引** `idx_drug_reg_name` / `idx_drug_product` / `idx_drug_manuf` / `idx_drug_approval` / `idx_drug_base_code`

#### `yp_codes`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | INTEGER PK | 自增主键 |
| `code` | TEXT UNIQUE | 药品代码 |
| `reg_name` / `product_name` / `manufacturer` / `approval_no` / `base_code` | TEXT | 同 `drug_detail` |
| `reg_dosage_form` / `reg_spec` / `dosage_form` / `spec` / `packaging` | TEXT | 同 `drug_detail` |
| `min_pkg_qty` / `min_prep_unit` / `min_pkg_unit` | TEXT | 同 `drug_detail` |
| `list_class` | TEXT | 甲/乙类 |

**索引** `idx_yp_code` / `idx_yp_mfr` / `idx_yp_approval`

### 3.2 `consumable_codes` 医保医用耗材

89,279 条，NHSA 医用耗材分类与代码 PDF 入库结果。

| 字段 | 类型 | 填充率 | 说明 |
|---|---|---:|---|
| `id` | id | 100.0% | INTEGER PK |
| `code` | code | 100.0% | TEXT UNIQUE |
| `cat_l1` | cat_l1 | 100.0% | 一级分类代码 |
| `cat_l1_name` | cat_l1_name | 100.0% | 一级分类名（18 大类） |
| `cat_l2` | cat_l2 | 99.8% | 二级分类代码 |
| `cat_l2_name` | cat_l2_name | 100.0% | 二级分类名 |
| `cat_l3` | cat_l3 | 91.9% | 三级分类代码 |
| `cat_l3_name` | cat_l3_name | 100.0% | 三级分类名 |
| `generic_category` | generic_category | 100.0% | 通用名分类 |
| `material` | material | 100.0% | 材质 |
| `spec` | spec | 100.0% | 规格 |
| `generic_no` | generic_no | 14.2% | 通用名编号 |
| `generic_name` | generic_name | 14.2% | 通用名 ⚠ 仅 14.2% 填充 |
| `manufacturer` | manufacturer | 100.0% | 生产厂家 100% |

**索引** `idx_cc_l1` / `idx_cc_l2` / `idx_cc_l3` / `idx_cc_generic` / `idx_cc_mfr`

### 3.3 `consumable7_codes` 7 大类医用耗材

3,728 条，**精选补全**版（每条都有 generic_name），用于医保编码与厂家检索。

字段同 `consumable_codes`（含 `cat_l1` / `cat_l2` / `cat_l3` / `generic_name` / `manufacturer` 等），填充率 100%。

**索引** `idx_cc7_l1` / `idx_cc7_l2` / `idx_cc7_l3`

### 3.4 `icd_codes` ICD-10 医保版疾病诊断

33,304 条，4 级层级：chapter > section > category > subcategory > diagnosis。

| 字段 | 类型 | 填充率 | 说明 |
|---|---|---:|---|
| `id` | id | 100.0% | INTEGER PK |
| `code` | code | 100.0% | ICD-10 编码 UNIQUE |
| `chapter_no` | chapter_no | 100.0% | 章号 (1-22) |
| `chapter_range` | chapter_range | 100.0% | 章号范围 |
| `chapter_name` | chapter_name | 100.0% | 章名 100% |
| `section_range` | section_range | 100.0% | 节范围 |
| `section_name` | section_name | 100.0% | 节名 |
| `category_code` | category_code | 100.0% | 类目代码 |
| `category_name` | category_name | 100.0% | 类目名 |
| `subcategory_code` | subcategory_code | 96.8% | 亚目代码 |
| `subcategory_name` | subcategory_name | 96.8% | 亚目名 96.8% |
| `diagnosis_code` | diagnosis_code | 100.0% | 诊断代码 |
| `diagnosis_name` | diagnosis_name | 100.0% | 诊断名 100% |

**索引** `idx_icd_chap` / `idx_icd_cat` / `idx_icd_sub` / `idx_icd_diag`

### 3.5 `ivd_codes` 医保体外诊断试剂

79,009 条，3 级分类（l1/l2/l3）。

| 字段 | 类型 | 填充率 | 说明 |
|---|---|---:|---|
| `id` | id | 100.0% | INTEGER PK |
| `code` | code | 100.0% | 试剂代码 UNIQUE |
| `cat_l1` | cat_l1 | 0.0% | 一级分类 |
| `cat_l1_name` | cat_l1_name | 100.0% | 一级分类名 |
| `cat_l2` | cat_l2 | 0.0% | 二级分类 |
| `cat_l2_name` | cat_l2_name | 100.0% | 二级分类名 |
| `cat_l3` | cat_l3 | 0.0% | 三级分类 |
| `cat_l3_name` | cat_l3_name | 100.0% | 三级分类名 |
| `testing_category` | testing_category | 100.0% | 检测类别 |
| `testing_index` | testing_index | 100.0% | 检测指标 |
| `use_type` | use_type | 100.0% | 使用类型 |
| `check_type` | check_type | 100.0% | 检查类型 |
| `company_name` | company_name | 100.0% | 生产企业 100% (2,672 唯一) |
| `business_license` | business_license | 0.0% | 营业执照号 |
| `spec_code` | spec_code | 0.0% | 规格代码 |
| `catalog_full_name` | catalog_full_name | 100.0% | 目录全名 |

**索引** `idx_ivd_l1` / `idx_ivd_l2` / `idx_ivd_l3` / `idx_ivd_test` / `idx_ivd_company`

### 3.6 `medical_service_codes` 医保医疗服务项目

8,220 条，15 位代码。

| 字段 | 类型 | 填充率 | 说明 |
|---|---|---:|---|
| `id` | id | 100.0% | INTEGER PK |
| `code` | code | 100.0% | 15 位项目代码 UNIQUE |
| `p_code` | p_code | 99.9% | 父级代码 |
| `name` | name | 100.0% | 项目名称 100% |
| `level` | level | 100.0% | 层级 (1-4) |
| `level_path` | level_path | 100.0% | 层级路径 |
| `pinyin_code` | pinyin_code | 0.0% | 拼音码 |
| `contains_content` | contains_content | 22.2% | 包含内容说明 |
| `excluded_content` | excluded_content | 8.5% | 不包含内容说明 |
| `charge_unit` | charge_unit | 94.0% | 计价单位 |
| `explain` | explain | 9.6% | 项目说明 ⚠ 仅 9.6% 填充 |
| `area` | area | 100.0% | 适用范围 |
| `is_using` | is_using | 100.0% | 是否启用 (0/1) |

**索引** `idx_ms_code` / `idx_ms_pcode` / `idx_ms_level`

### 3.7 `tcm_codes` 中医病证术语与代码

1,369 条，GB/T 15657-1995 中医病证分类与代码。

| 字段 | 类型 | 填充率 | 说明 |
|---|---|---:|---|
| `id` | id | 100.0% | INTEGER PK |
| `code` | code | 100.0% | A 前缀代码 (A01.01.01) UNIQUE |
| `p_code` | p_code | 100.0% | 父级代码 |
| `name` | name | 100.0% | 病证名称 100% |
| `part_code` | part_code | 100.0% | 部位代码 |
| `code_length` | code_length | 100.0% | 代码层级深度 |
| `level` | level | 100.0% | 层级 |
| `apply_explain` | apply_explain | 0.0% | 适用范围说明 ⚠ 0% 填充（待补） |
| `remark` | remark | 0.0% | 备注 |
| `class_code` | class_code | 0.0% | 分类代码 |
| `class_name` | class_name | 100.0% | 分类名 |

**索引** `idx_tcm_code` / `idx_tcm_pcode`

## 4. FTS5 全文索引

8 个 FTS5 虚拟表，配 24 个 trigger (ai/au/ad) 保持同步。所有 FTS5 使用 `unicode61 remove_diacritics 2` 分词器，按字符切分（中文按字），搜索时必须用前缀匹配（`MATCH 'xxx*'`）。

| FTS5 表 | 对应主表 | 索引字段 |
|---|---|---|
| `kp_fts` | `knowledge_points` | subject_name, detection_logic, logic_basis, remark, codes |
| `drug_fts` | `drug_detail` | reg_name, product_name, manufacturer, approval_no |
| `yp_codes_fts` | `yp_codes` | code, reg_name, product_name, manufacturer, approval_no |
| `consumable_codes_fts` | `consumable_codes` | code, generic_name, manufacturer, generic_no, cat_l1_name, cat_l2_name, cat_l3_name |
| `icd_codes_fts` | `icd_codes` | code, chapter_name, section_name, category_name, subcategory_name, diagnosis_name |
| `ivd_codes_fts` | `ivd_codes` | code, cat_l1_name, cat_l2_name, cat_l3_name, testing_category, testing_index, company_name |
| `medical_service_codes_fts` | `medical_service_codes` | code, name, explain, contains_content, excluded_content |
| `tcm_codes_fts` | `tcm_codes` | code, name, class_name, apply_explain, remark |

**rebuild 命令**（数据全量修改后用）：

```sql
INSERT INTO kp_fts(kp_fts) VALUES('rebuild');
-- 同理 consumable_codes_fts / drug_fts / yp_codes_fts / icd_codes_fts / ivd_codes_fts / medical_service_codes_fts / tcm_codes_fts
```

### 4.1 FTS5 触发器（24 个）

每张 FTS5 表配 3 个 trigger：

- `*_ai` AFTER INSERT → 把新行同步到 FTS5

- `*_au` AFTER UPDATE → 删除旧行 + 插入新行（保持 FTS5 一致）

- `*_ad` AFTER DELETE → 从 FTS5 删行

所有 FTS5 都是 **external content** 模式（`content='主表'`），数据存在主表，FTS5 只存索引。

## 5. 辅助表

### 5.1 `nhsa_batches` NHSA 抓取批次元数据

8 条，记录 `webapp/ingest_nhsa_dbs.py` 抓取 NHSA 各分类数据库的元数据。

| 字段 | 类型 | 说明 |
|---|---|---|
| `source` | TEXT PK | 抓取来源标识（如 `nhsa_yp_drugs`） |
| `batch_label` | TEXT | 显示名 |
| `pub_date` | TEXT | 抓取时点 |
| `ann_url` | TEXT | NHSA 公告 URL |
| `pdf_path` / `csv_path` / `json_path` | TEXT | 本地落盘路径 |
| `record_count` | INTEGER | 抓取记录数 |
| `sysflag` | TEXT | NHSA sysflag 参数 |
| `ingested_at` | TEXT | 入库时间戳 |

## 6. 关系图

```
              ┌──────────────┐
              │   batches    │
              │ (17 批次)    │
              └──────┬───────┘
                     │ 1:N
              ┌──────▼───────┐
              │    rules     │
              │  (77 规则)   │
              └──────┬───────┘
                     │ 1:N
              ┌──────▼───────────┐         ┌──────────────────┐
              │ knowledge_points │◄────────│ kp_fts (FTS5)    │
              │   (21,658 KP)    │         └──────────────────┘
              └──────┬───────────┘
                     │ 1:N
              ┌──────▼─────────────────┐
              │ knowledge_point_codes  │
              │     (29,872)           │
              └──────┬─────────────────┘
                     │ N:1 (code)
       ┌─────────────┼─────────────┬────────────────┐
       ▼             ▼             ▼                ▼
  ┌─────────┐  ┌────────────┐  ┌─────────────┐  ┌────────────┐
  │yp_codes │  │drug_detail │  │medical_serv │  │consumable  │
  │(260,692)│  │ (260,692)  │  │  (8,220)    │  │  (89,279)  │
  └─────────┘  └────────────┘  └─────────────┘  └────────────┘
       │             │             │                │
       ▼             ▼             ▼                ▼
  yp_codes_fts  drug_fts   medical_service_f  consumable_f
```

## 7. 关键约定

1. **外键 CASCADE**：`batches / rules / knowledge_points / knowledge_point_codes` 之间 CASCADE 删除；删一批会清掉所有下层。
2. **codes 字段多码分隔符**：`・` (U+30FB 日文中点) 用于同一 KP 关联多个医保编码，例如 `XL02BBA326A001010102180・XL02BBA326A001010178537・XL02BBA326A001020278537`
3. **`drug_detail.manufacturer` 清洗**（2026-06-28 起）：
   - 原始值保留在 `manufacturer_raw`
   - `manufacturer_flag` 标记状态：NULL=✓ / `⚠混入规格` / `⚠过短` / `⚠空` / `⚠过长`
   - 99.98% 行通过清洗（清洗脚本 `webapp/clean_drug_detail.py`，幂等）
4. **FTS5 中文搜索**：`unicode61` 按字分词，必须用前缀匹配 `MATCH '艾附*'`，短语 `"艾附暖宫丸"` 返回 0。
5. **`raw_row` 保留**：所有 KP 保留 PDF 原始行 JSON（用于 `parse_kp_partner()` 解析 service/pair 的配对项目）。
6. **CRUD 同步**：FTS5 trigger 自动维护；如做大批量 UPDATE，建议先 `PRAGMA journal_mode=WAL` + `synchronous=NORMAL`。

## 8. 常用 SQL 示例

```sql
-- 1. 查某 KP 的所有医保编码 + 厂家
SELECT kp.subject_name, kpc.code, dd.manufacturer, dd.manufacturer_flag
FROM knowledge_points kp
JOIN knowledge_point_codes kpc ON kpc.kp_id = kp.id
LEFT JOIN drug_detail dd ON dd.goods_code = kpc.code
WHERE kp.id = ?;

-- 2. 按医保编码反查 KP 列表
SELECT kp.id, kp.subject_name, b.batch_label, r.rule_subject
FROM knowledge_point_codes kpc
JOIN knowledge_points kp ON kp.id = kpc.kp_id
JOIN rules r ON r.id = kp.rule_id
JOIN batches b ON b.id = r.batch_id
WHERE kpc.code = ?;

-- 3. 按 object_type 统计 KP × 编码
SELECT r.object_type,
       COUNT(DISTINCT kp.id) AS kp_cnt,
       COUNT(DISTINCT kpc.code) AS uniq_codes
FROM knowledge_points kp
JOIN rules r ON r.id = kp.rule_id
LEFT JOIN knowledge_point_codes kpc ON kpc.kp_id = kp.id
GROUP BY r.object_type;

-- 4. 全文搜 KP（前缀匹配）
SELECT kp.id, kp.subject_name FROM kp_fts
JOIN knowledge_points kp ON kp.id = kp_fts.rowid
WHERE kp_fts MATCH '艾附*' LIMIT 20;

-- 5. 重建 FTS5
INSERT INTO kp_fts(kp_fts) VALUES('rebuild');
```

## 9. 数据来源与版本

| 表 | 主要来源 | 数据时点 |
|---|---|---|
| `yp_codes` / `drug_detail` | NHSA 医保药品分类与代码 CSV (`原始数据/YP/医保药品_20260625.csv`) | 2026-06-25 |
| `consumable_codes` | NHSA 医保医用耗材分类与代码 CSV (`原始数据/HC/医保医用耗材_20260626.csv`) | 2026-06-26 |
| `consumable7_codes` | 精选 7 大类（人工核验） | 2026-06-26 |
| `icd_codes` | ICD-10 国标版 (`原始数据/ICD/ICD_20210114.csv`) | 2021-01-14 |
| `ivd_codes` | NHSA 体外诊断试剂 (`原始数据/IVD/体外诊断试剂_20260611.csv`) | 2026-06-11 |
| `tcm_codes` | GB/T 15657 中医病证分类 (`原始数据/TCM/all.json`) | — |
| `medical_service_codes` | 医疗服务项目代码 PDF | 2026-06-12 解析 |
| `knowledge_points` / `rules` / `batches` | NHSA 第一批 ~ 第十六批 XLSX + 2025 PDF 合并版 | 2025-2026 |

## 10. 备份与恢复

- 本地备份：`webapp/data/kp.db.bak.20260629_081613` (清理无效字符前，434 MB)
- 服务端同步：`/opt/medical-audit/webapp/data/kp.db` (434 MB)
- 历史归档：`_kpc_backup_20260629` 表 (93 条 service KP 的 codes 备份，P0.1 操作前的原始数据)
- WAL 模式：运行时 `kp.db-wal` / `kp.db-shm` 自动生成；不要在服务运行时直接复制主文件
