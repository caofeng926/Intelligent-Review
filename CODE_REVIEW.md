# 代码审查标准与流程

> 适用于「医保智审规则库」项目 — Flask + SQLite + Jinja2 技术栈
>
> 制定日期：2026-07-05 | 版本：v1.0

---

## 目录

1. [审查流程](#1-审查流程)
2. [提交前自检清单](#2-提交前自检清单)
3. [审查标准](#3-审查标准)
   - 3.1 [安全性](#31-安全性)
   - 3.2 [正确性](#32-正确性)
   - 3.3 [可维护性](#33-可维护性)
   - 3.4 [性能](#34-性能)
   - 3.5 [前端](#35-前端)
   - 3.6 [数据库与 SQL](#36-数据库与-sql)
4. [PR 模板](#4-pr-模板)
5. [审查者指南](#5-审查者指南)
6. [自动化工具链](#6-自动化工具链)
7. [已知技术债清单](#7-已知技术债清单)

---

## 1. 审查流程

```
开发者                          审查者
  │
  ├── 1. 本地通过自检清单 ──────────────────────────────┐
  │                                                     │
  ├── 2. 创建分支: feat/fix/refactor-<简述>             │
  │                                                     │
  ├── 3. 提交 PR (使用模板)                              │
  │         │                                           │
  │         ▼                                           │
  │    ┌────────────────────────────────┐               │
  │    │  自动化检查 (pre-commit / CI)   │               │
  │    │  · flake8 语法检查              │               │
  │    │  · 安全扫描 (detect-secrets)    │               │
  │    │  · 导入排序 (isort)             │               │
  │    └───────────┬────────────────────┘               │
  │                │                                    │
  │           通过? ├─ 否 → 退回修改                     │
  │                │                                    │
  │                ▼ 是                                 │
  │    ┌────────────────────────────────┐               │
  │    │  人工审查 (至少 1 人)            │ ◄────────────┘
  │    │  · 按 §3 标准逐项检查            │
  │    │  · 标注优先级 (🔴🟡💭)          │
  │    │  · 24h 内给出反馈               │
  │    └───────────┬────────────────────┘               │
  │                │                                    │
  │           通过? ├─ 有 🔴 → 修改后重新审查            │
  │                │    仅 🟡💭 → 讨论后可合并           │
  │                ▼ 是                                 │
  ├── 4. 合并到 main ───────────────────────────────────
  │
  └── 5. 删除分支
```

### 角色与职责

| 角色 | 职责 |
|---|---|
| **提交者** | 自检通过后再提交；PR 描述清晰；及时响应审查意见 |
| **审查者** | 24h 内响应；聚焦正确性/安全/可维护性；给出可操作的建议 |
| **合并者** | 确认所有 🔴 blocker 已解决；确认 CI 通过 |

### 审查规模指导

- 单次 PR 控制在 **400 行变更以内**，超过则拆分
- 审查者单次审查时间 **不超过 60 分钟**，超时则分批
- 审查意见 **不超过 48h** 未响应，可提醒提交者

---

## 2. 提交前自检清单

提交者在创建 PR 前必须逐项确认：

### 通用

- [ ] 代码能在本地正常运行
- [ ] 没有遗留的 `print()` 调试语句（入库脚本除外）
- [ ] 没有遗留的 `.bak` 备份文件
- [ ] 没有硬编码的密码、密钥、服务器凭据
- [ ] 没有硬编码的绝对路径（如 `C:\Users\...`、`/opt/medical-audit/...`）

### Python

- [ ] 所有 `except` 块都记录了异常（无裸 `except:` 或 `except: pass`）
- [ ] 所有用户输入的 `int()` 转换有 try/except 保护
- [ ] 所有 SQL 查询使用 `?` 参数化（值部分）
- [ ] f-string 拼接的表名/列名来自内部常量（非用户输入）
- [ ] 新增函数有 docstring（至少一行说明）
- [ ] 无明显的代码重复（超过 10 行的重复块应提取为函数）

### 前端

- [ ] 所有动态插入 HTML 的内容经过 `escapeHtml` 或使用 `textContent`
- [ ] 所有 `fetch` 请求有错误处理
- [ ] 新增 CSS 使用 `--c-*` 设计令牌，不硬编码颜色值
- [ ] 图标使用 inline SVG，不使用 Unicode 符号

---

## 3. 审查标准

优先级标记：

| 标记 | 含义 | 处理方式 |
|---|---|---|
| 🔴 | **Blocker** — 安全漏洞、数据损坏、崩溃 | 必须修复后才能合并 |
| 🟡 | **Should Fix** — 输入验证缺失、代码重复、性能问题 | 应在本 PR 或下一 PR 修复 |
| 💭 | **Nit** — 命名、注释、风格 | 可讨论，不阻塞合并 |

---

### 3.1 安全性

#### SEC-01: 禁止硬编码凭据 🔴

**规则**: 密码、密钥、Token、SSH 凭据不得出现在代码中。

```python
# 🔴 禁止
PASS = "***REDACTED***"
ssh.connect("43.136.175.219", password="***REDACTED***")

# ✅ 正确
PASS = os.environ.get("MA_SSH_PASS")
if not PASS:
    raise RuntimeError("环境变量 MA_SSH_PASS 未设置")
```

**审查要点**: 搜索 `password=`、`secret=`、`key=`、`token=` 等关键词。

#### SEC-02: SQL 参数化 🔴

**规则**: 所有 SQL 值必须使用 `?` 占位符。表名/列名只能来自内部白名单常量。

```python
# 🔴 禁止 — 用户输入直接拼接
sql = f"SELECT * FROM {table} WHERE name = '{user_input}'"

# 🟡 警惕 — f-string 拼接表名（需确认 table 来自常量白名单）
rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchall()

# ✅ 正确 — 值用 ?，表名来自常量
_TABLES = frozenset({"knowledge_points", "drug_detail", "consumable_codes"})
if table not in _TABLES:
    raise ValueError(f"非法表名: {table}")
rows = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchall()
```

#### SEC-03: 用户输入验证 🟡

**规则**: 所有 `request.args.get()` / `request.form.get()` 的值在类型转换前必须验证。

```python
# 🔴 禁止 — ValueError 导致 500
page = int(request.args.get("page", 1))

# ✅ 正确
def _safe_int(value, default=1, min_val=1, max_val=None):
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    n = max(min_val, n)
    if max_val:
        n = min(n, max_val)
    return n

page = _safe_int(request.args.get("page", 1), default=1, min_val=1, max_val=10000)
```

#### SEC-04: Debug 模式控制 🔴

**规则**: Flask debug 模式必须通过环境变量控制，默认关闭。

```python
# 🔴 禁止 — 命令行参数可能被误用
ap.add_argument("--debug", action="store_true")
app.run(debug=args.debug)

# ✅ 正确
debug = os.environ.get("FLASK_DEBUG", "0") == "1"
app.run(debug=debug)
```

#### SEC-05: XSS 防护 🟡

**规则**: 前端所有动态 HTML 必须转义。Jinja2 模板中使用 `|safe` 过滤器时必须确认内容可信。

```javascript
// 🔴 禁止
el.innerHTML = data.name;

// ✅ 正确
el.textContent = data.name;
// 或
el.innerHTML = escapeHtml(data.name);
```

---

### 3.2 正确性

#### COR-01: 异常处理不得静默吞错 🔴

**规则**: `except` 块必须记录异常或明确说明为何忽略。

```python
# 🔴 禁止 — 静默吞没所有异常
try:
    conn.executescript(p)
except:
    pass

# 🔴 禁止 — 吞掉异常不记录
except Exception:
    pass

# ✅ 正确
except Exception as e:
    logging.warning(f"Schema 部分创建失败，跳过: {e}")

# ✅ 正确 — 明确说明为何忽略
except sqlite3.OperationalError:
    pass  # FTS5 触发器已存在，预期行为
```

#### COR-02: 数据库变更计数 🟡

**规则**: 统计单条 SQL 语句影响的行数，使用 `cursor.rowcount`，**不要**使用 `connection.total_changes`（后者是连接生命周期内的累计值）。

```python
# 🔴 错误 — total_changes 是累计值
c.execute("UPDATE ... SET flag='⚠空' WHERE ...")
counts["⚠空"] = c.total_changes  # 包含之前所有语句的变更

# ✅ 正确
cur = c.execute("UPDATE ... SET flag='⚠空' WHERE ...")
counts["⚠空"] = cur.rowcount
```

#### COR-03: 上下文管理器一致性 🟡

**规则**: 数据库连接统一使用 `db.connect()` 上下文管理器，不直接调用 `sqlite3.connect()`。

```python
# 🟡 不推荐 — 绕过统一事务管理
c = sqlite3.connect(db_path)
c.execute("PRAGMA journal_mode=WAL")
# ... 散落的手动 commit
c.commit()

# ✅ 正确
from webapp.db import connect
with connect(db_path) as conn:
    conn.execute("...")
    # 自动 commit/rollback/close
```

**例外**: 需要特殊 PRAGMA（如 `cache_size=-200000`）的批量入库脚本可例外，但需在代码注释说明原因。

#### COR-04: row_factory 恢复 🟡

**规则**: 不要在共享连接上临时切换 `row_factory` 再恢复。如果需要 Row 访问，在 `connect()` 中全局设置或使用独立连接。

```python
# 🟡 脆弱 — 异常时 row_factory 不会恢复
conn.row_factory = sqlite3.Row
rows = conn.execute(sql).fetchall()
conn.row_factory = None  # 异常时不会执行

# ✅ 正确 — 使用独立连接或全局设置
with connect() as conn:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql).fetchall()
    # 连接关闭时自动清理
```

---

### 3.3 可维护性

#### MAINT-01: 消除代码重复 🟡

**规则**: 超过 10 行的重复逻辑必须提取为公共函数。

已知重复点（必须逐步消除）：

| 重复内容 | 出现位置 | 应提取为 |
|---|---|---|
| FTS5 查询构建 | `app.py`, `nhsa_api.py`, `admin.py` | `webapp/query_utils.py:build_fts_query()` |
| 分类映射逻辑 | `app.py:rules_category()` + `api_rule_categories()` | `webapp/categorize.py` |
| NHSA 表计数 | `nhsa_browse.py`, `admin.py`, `nhsa_api.py` | `webapp/nhsa_utils.py:counts()` |
| 耗材详情查询 (13列) | `app.py` ×3, `nhsa_browse.py` ×1 | `webapp/consumable.py:get_detail()` |
| `dict(zip(keys, row))` | 30+ 处 | 统一使用 `sqlite3.Row` 或数据类 |

#### MAINT-02: 函数/文件长度 💭

| 对象 | 建议上限 | 当前最大 | 状态 |
|---|---|---|---|
| 单个函数 | 50 行 | — | — |
| 单个 `.py` 文件 | 500 行 | `app.py` 1111 行 | ⚠️ 需拆分 |
| 单个 `.css` 文件 | 1500 行 | `mobile.css` ~1900 行 | ⚠️ 可拆分 |
| 单个 `.js` 文件 | 800 行 | — | — |
| 单个模板文件 | 300 行 | — | — |

#### MAINT-03: 命名规范 💭

| 类型 | 规范 | 示例 |
|---|---|---|
| Python 函数/变量 | `snake_case` | `build_fts_query` |
| Python 类 | `PascalCase` | `DrugDetail` |
| Python 常量 | `UPPER_SNAKE` | `DB_PATH` |
| Python 私有 | `_` 前缀 | `_safe_int` |
| CSS 类 | `kebab-case` | `.card-header` |
| JS 变量 | `camelCase` | `escapeHtml` |
| 数据库表 | `snake_case` | `knowledge_points` |
| 临时脚本 | `_` 前缀 | `_check_db.py` |

#### MAINT-04: Docstring 要求 🟡

**规则**: 所有公共函数必须有 docstring。私有函数（`_` 前缀）至少一行注释说明意图。

```python
# ✅ 公共函数
def build_fts_query(q: str) -> str:
    """构建 FTS5 MATCH 表达式。

    FTS5 unicode61 按单字分词，中文短语匹配无效，
    因此使用前缀匹配 (token*) 替代。

    Args:
        q: 用户搜索词

    Returns:
        FTS5 MATCH 表达式字符串
    """
```

#### MAINT-05: 编码一致性 🔴

**规则**: 所有 `.py` 文件必须使用 UTF-8 编码，不得出现 GBK/UTF-8 混淆导致的乱码。

**当前问题**: `db.py` Schema 注释中存在严重乱码（如 `瀵瑰簲鐭ヨ瘑鐐瑰簭鍙?` 应为 `对应知识点序号`）。

---

### 3.4 性能

#### PERF-01: 避免 N+1 查询 🟡

**规则**: 循环中不得执行 SQL 查询。使用 JOIN 或批量查询。

```python
# 🔴 禁止 — N+1 查询
for kp in knowledge_points:
    codes = conn.execute("SELECT * FROM codes WHERE kp_id = ?", (kp["id"],)).fetchall()

# ✅ 正确 — 批量查询
kp_ids = [kp["id"] for kp in knowledge_points]
placeholders = ",".join("?" * len(kp_ids))
all_codes = conn.execute(
    f"SELECT * FROM codes WHERE kp_id IN ({placeholders})", kp_ids
).fetchall()
```

#### PERF-02: 静态文件缓存 🟡

**规则**: 生产环境必须启用静态文件缓存。

```python
# 🔴 当前 — 全局禁用缓存
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# ✅ 正确 — 仅 debug 时禁用
if app.debug:
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
else:
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 31536000  # 1 年
```

#### PERF-03: 数据库 PRAGMA 🟡

**规则**: 所有数据库连接必须设置 WAL 模式和合理的 PRAGMA。

```python
# ✅ 已在 db.connect() 中正确设置
conn.execute("PRAGMA journal_mode = WAL")
conn.execute("PRAGMA synchronous = NORMAL")
conn.execute("PRAGMA foreign_keys = ON")
```

#### PERF-04: FTS5 前缀匹配限制 💭

**规则**: FTS5 查询的前缀匹配 (`token*`) 已是当前最佳方案。如需改进，考虑迁移到 `trigram` 分词器（SQLite ≥ 3.34）。

---

### 3.5 前端

#### FE-01: 设计令牌 🟡

**规则**: 新增样式必须使用 `--c-*` CSS 变量，不硬编码颜色/间距。

```css
/* 🔴 禁止 */
.card { background: #0284C7; padding: 16px; }

/* ✅ 正确 */
.card { background: var(--c-primary); padding: var(--space-md); }
```

#### FE-02: SVG 图标 💭

**规则**: 所有图标使用 inline SVG，不使用 Unicode 符号（⌕ ∅ ≡ ⊞ ⓘ 等）。

#### FE-03: 事件委托 🟡

**规则**: 动态生成的元素使用事件委托，不逐个绑定。

```javascript
// ✅ 事件委托
document.addEventListener("click", (e) => {
    const btn = e.target.closest(".copy-btn");
    if (!btn) return;
    // ...
});
```

#### FE-04: 错误处理 🟡

**规则**: 所有 `fetch` 请求必须有 `.catch()` 或 `try/catch`。

```javascript
// ✅ 正确
try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
} catch (err) {
    showToast("加载失败: " + err.message);
}
```

---

### 3.6 数据库与 SQL

#### DB-01: Schema 变更 🔴

**规则**: 任何 Schema 变更必须：
1. 在 `db.py` 的 SCHEMA/EXTRA_SCHEMA 中修改
2. 提供 migration 脚本（非 `--reset` 模式下可执行）
3. 更新 AGENTS.md 中的表结构文档

#### DB-02: 索引覆盖 🟡

**规则**: 所有 WHERE 条件中的字段必须有索引。新增查询需检查 `EXPLAIN QUERY PLAN`。

```python
# 审查时验证
conn.execute("EXPLAIN QUERY PLAN SELECT * FROM drug_detail WHERE manufacturer = ?", ("国药",)).fetchall()
# 确认使用了索引而非全表扫描
```

#### DB-03: 事务边界 🟡

**规则**: 入库操作必须在单个事务中完成（使用 `with connect() as conn:`），确保原子性。

#### DB-04: FTS5 触发器同步 🟡

**规则**: 修改基础表数据后，确认 FTS5 触发器正常同步。批量 DELETE + INSERT 时特别注意。

---

## 4. PR 模板

创建 PR 时复制以下模板填写：

```markdown
## 变更说明

<!-- 一句话说明本 PR 做了什么 -->

## 变更类型

- [ ] feat: 新功能
- [ ] fix: 修复 Bug
- [ ] refactor: 重构
- [ ] perf: 性能优化
- [ ] docs: 文档
- [ ] chore: 杂项

## 影响范围

<!-- 列出受影响的模块/表/路由 -->

## 测试方式

<!-- 描述如何验证本次变更 -->

## 自检清单

- [ ] 无硬编码凭据
- [ ] 无裸 except: pass
- [ ] 用户输入已验证
- [ ] SQL 参数化
- [ ] 无 .bak 残留
- [ ] 无 print() 调试语句（入库脚本除外）

## 截图/输出（如适用）

<!-- 前端变更附截图，API 变更附 curl 示例 -->
```

---

## 5. 审查者指南

### 审查顺序

1. **先看整体** — PR 描述、变更文件列表、diff 概览
2. **安全性优先** — 搜索凭据、检查 SQL、验证输入
3. **正确性** — 理解业务逻辑，检查边界条件
4. **可维护性** — 重复代码、命名、函数长度
5. **性能** — N+1 查询、不必要的全表扫描
6. **最后看风格** — 命名、注释、格式

### 评论规范

```
🔴 [安全] SQL 注入风险
Line 42: 用户输入通过 f-string 拼接进 SQL 表名。

原因: 如果 table 变量被用户可控的输入污染，可构造恶意表名。

建议: 使用白名单校验
```python
_ALLOWED_TABLES = frozenset({"knowledge_points", "drug_detail"})
if table not in _ALLOWED_TABLES:
    raise ValueError(f"非法表名: {table}")
```
```

### 审查者"不要"做的事

- ❌ 不要纠结个人风格偏好（用 linter 解决）
- ❌ 不要要求完美（"好"优于"完美"）
- ❌ 不要在 💭 nit 上消耗过多时间
- ❌ 不要重写提交者的代码（给建议，让提交者改）
- ❌ 不要沉默 — 如果没问题，明确说 "LGTM" 并说明好在哪里

### 审查者"应该"做的事

- ✅ 先肯定好的设计，再提建议
- ✅ 对每条意见解释"为什么"
- ✅ 提供具体的修复代码示例
- ✅ 区分"必须改"和"建议改"
- ✅ 24h 内响应

---

## 6. 自动化工具链

### 推荐配置

在项目根目录创建以下配置文件：

#### `.flake8`

```ini
[flake8]
max-line-length = 120
extend-ignore = E203, W503
exclude =
    .git,
    __pycache__,
    _*.py,
    *.bak,
    webapp/data/
per-file-ignores =
    webapp/ingest_*.py: E501
```

#### `pyproject.toml` (isort)

```toml
[tool.isort]
profile = "black"
line_length = 120
skip = ["_*.py", "webapp/data"]
```

#### `.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/PyCQA/flake8
    rev: '7.1.1'
    hooks:
      - id: flake8

  - repo: https://github.com/PyCQA/isort
    rev: '5.13.2'
    hooks:
      - id: isort

  - repo: https://github.com/Yelp/detect-secrets
    rev: '1.5.0'
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']

  - repo: local
    hooks:
      - id: no-bak-files
        name: 禁止提交 .bak 文件
        entry: bash -c 'git diff --cached --name-only | grep -q "\.bak" && echo "禁止提交 .bak 文件" && exit 1 || exit 0'
        language: system
        pass_filenames: false
```

#### `requirements-dev.txt`

```
flake8>=7.0
isort>=5.13
detect-secrets>=1.5
pre-commit>=3.6
```

### 安装步骤

```bash
pip install -r requirements-dev.txt
pre-commit install
pre-commit run --all-files  # 首次全量检查
```

---

## 7. 已知技术债清单

以下问题在首次代码审查中发现，按优先级排序。新 PR 不应加剧这些问题，鼓励在相关变更中顺带修复。

### 🔴 立即处理

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| TD-01 | SSH 密码硬编码 | `AGENTS.md`, `scripts/sync_yp2023_to_cvm.py`, `scripts/_ssh.py`, `webapp/_wait_upload.py` | 轮换密码，改用环境变量/SSH Key |
| TD-02 | `total_changes` 统计错误 | `clean_drug_detail.py:138-165` | 改用 `cursor.rowcount` |
| TD-03 | 裸 `except: pass` | `db.py:202` | 改为记录日志 |
| TD-04 | 编码乱码 | `db.py` Schema 注释 (多处) | 重新用 UTF-8 编写注释 |
| TD-05 | Debug 模式可通过命令行开启 | `app.py:1109-1111` | 改用环境变量 |

### 🟡 近期处理

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| TD-06 | FTS 查询函数重复 3 次 | `app.py`, `nhsa_api.py`, `admin.py` | 提取为公共函数 |
| TD-07 | `int()` 未验证 | `app.py:285`, `admin.py:175`, `nhsa_browse.py:451` | 添加 try/except |
| TD-08 | `app.py` 过大 (1111 行) | `app.py` | 拆分为多个模块 |
| TD-09 | `dict(zip(keys, row))` 重复 30+ 处 | 全局 | 统一使用 `sqlite3.Row` |
| TD-10 | 静态文件缓存禁用 | `app.py:37` | 仅 debug 时禁用 |
| TD-11 | `requirements.txt` 不完整 | `webapp/requirements.txt` | 添加 gunicorn, paramiko；固定版本 |
| TD-12 | `row_factory` 临时切换 | `app.py:636-662` | 使用独立连接或全局设置 |
| TD-13 | 无 lint/format 配置 | 项目根目录 | 添加 .flake8 + pre-commit |

### 💭 适时处理

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| TD-14 | 87 个临时脚本 | 项目根目录 `_*.py` | 归档或删除 |
| TD-15 | .bak 文件残留 | `webapp/*.bak.*` | 清理 |
| TD-16 | 无正式测试 | — | 添加关键路径的单元测试 |
| TD-17 | `clean_drug_detail.py` 绕过 `db.connect()` | `clean_drug_detail.py:215` | 统一使用上下文管理器 |
| TD-18 | 分类映射逻辑重复 | `app.py:478-507` + `1054-1083` | 提取为公共模块 |
| TD-19 | NHSA 表计数逻辑重复 3 处 | `nhsa_browse.py`, `admin.py`, `nhsa_api.py` | 提取为公共函数 |

---

## 附录: 审查快速参考卡

```
┌──────────────────────────────────────────────────────┐
│              代码审查快速参考卡                        │
├──────────────────────────────────────────────────────┤
│                                                      │
│  提交前:  自检清单 → pre-commit → 创建 PR             │
│  审查时:  安全 → 正确 → 可维护 → 性能 → 风格         │
│  评论时:  🔴必须 🟡建议 💭可选 + 解释原因 + 代码示例  │
│  合并前:  所有 🔴 已解决 + CI 通过                    │
│                                                      │
│  🔴 Blocker:  凭据泄露 / SQL注入 / 静默吞错 / 崩溃   │
│  🟡 ShouldFix: 输入验证 / 代码重复 / N+1 / 缓存      │
│  💭 Nit:      命名 / 注释 / 风格                     │
│                                                      │
│  记住: 好的审查教会东西，不只是找茬                   │
│                                                      │
└──────────────────────────────────────────────────────┘
```
