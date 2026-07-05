# 第三轮代码审查报告

> 审查日期：2026-07-05 (第三轮)
> 审查目的：验证第二轮报告的修复是否到位 + 新代码质量
> 对照标准：CODE_REVIEW.md v1.0 + CODE_REVIEW_R2.md 技术债清单

---

## 一、总体评价

进步很大。上轮报告的 3 个 🔴 残留中，2 个已完全修复，1 个部分修复。
更可贵的是，团队没有止步于"补漏"，而是主动推进了 🟡 项的重构——
`query_utils.py` 模块抽取、`consumables.py` 路由拆分、`row_to_dict` 统一、
静态缓存策略，都是高质量的架构改进。

**但有一个回归 bug 必须立即修复**：TD-06 重构时，`admin.py` 导入了新的
`fts_query` 但调用点仍用旧名 `_admin_fts_query`，导致管理后台搜索
功能运行时直接 NameError 崩溃。

---

## 二、上轮 🔴 残留复审

### TD-01: SSH 密码硬编码 → ✅ 完全修复

| 位置 | 上轮状态 | 本轮状态 |
|---|---|---|
| `webapp/_wait_upload.py` | 🟡 明文密码 | ✅ 文件已删除 |
| `AGENTS.md:56` | 🟡 明文密码 | ✅ 改为 `$MA_SSH_PASS` 环境变量 |
| `scripts/sync_yp2023_to_cvm.py` | ✅ 已修 | ✅ 保持 |
| `scripts/_ssh.py` | ✅ 已修 | ✅ 保持 |
| `scripts/sync_to_cvm.ps1` | ✅ 已修 | ✅ 保持 |

**代码层面已无明文密码。** ⚠️ 但密码 `***REDACTED***` 仍出现在三份审查文档中
（`CODE_REVIEW.md`、`CODE_REVIEW_R2.md`、`overview.md`），这些是审查报告
中的示例引用，不是活跃代码。若仓库已推送到远程，**建议轮换服务器密码**，
旧密码即使从 git 历史删除也已失效。

---

### TD-04: 编码乱码 → 🟡 大部分修复，5 处残留

上轮 db.py 有 10+ 处乱码，本轮大部分已修为正确的 UTF-8 中文。
**但仍有 5 处残留**：

| 行号 | 当前内容 | 应为 |
|---|---|---|
| 60 | `对应知识点序号?.` | `对应知识点序号)` |
| 96 | `医用耗材代码库?(from NHSA...` | `医用耗材代码库（from NHSA...` |
| 343 | `(銆?` | `（、）` |
| 513 | `閸忋劌娴楅崠鑖ゆ灍閺堝秴濮熸い鍦窗` | `医疗服务项目代码库` |
| 558 | `娑撹弓鑵戦崠鑖ゆ⒕/鐠囦椒绶?2.0 閻楋拷` | `中药饮片/民族药 2.0 版` |

前 3 处是标点符号编码损坏（`）`→`?.`、`（`→`?`），后 2 处是整行中文
完全乱码。纯注释修改，零风险。

---

### TD-05: Debug 模式 → 🟡 保持 (可接受)

与上轮相同：有 `FLASK_ENV=production` 互斥检查，生产用 gunicorn 不走
`__main__`。可接受当前方案。

---

## 三、🟡 项复审 — 重构进展

### TD-06: FTS 查询函数重复 → 🟡 工具已建，但有回归 bug

**做得好的部分：**
- `query_utils.py` 创建了统一的 `fts_query()` 函数 ✅
- `app.py:31` 已引用 `from .query_utils import fts_query as jieba_query` ✅
- `nhsa_browse.py:14` 已引用 `from .query_utils import fts_query as _fts_query` ✅
- `query_utils.fts_search()` 还封装了 FTS + LIKE fallback，设计周全 ✅

**🔴 回归 Bug — NEW-04: admin.py 悬空调用**

```python
# admin.py:19 — 导入了新函数
from .query_utils import fts_query     # ✅ 导入了

# admin.py:368 — 但调用的是旧名字！
fts = _admin_fts_query(q)              # ❌ _admin_fts_query 已不存在

# admin.py:613 — 同样的问题
fts = _admin_fts_query(q)              # ❌ NameError at runtime
```

全项目搜索确认：`_admin_fts_query` 的定义已不存在，仅剩这两处调用。
`fts_query` 导入后从未被使用（死导入）。

**影响**：用户在管理后台搜索（`/admin/search` 或 `/admin/kp/search`）
时，输入关键词提交后触发 `NameError: name '_admin_fts_query' is not defined`，
返回 500 错误。

**修复**（2 行改动）：
```python
# admin.py:368
fts = fts_query(q)          # was: _admin_fts_query(q)

# admin.py:613
fts = fts_query(q)          # was: _admin_fts_query(q)
```

---

### TD-07: int() 未验证 → 🟡 工具已建，12/13 调用点未迁移

`query_utils.py` 提供了 `page_from()` 和 `limit_from()`，设计完善
（带 min/max 钳位 + try/except）。**但几乎所有调用点都没迁移**：

| 文件 | 行号 | 当前代码 | 状态 |
|---|---|---|---|
| `app.py` | 267 | `int(request.args.get("page", 1) or 1)` | ❌ 未迁移 |
| `app.py` | 412 | 同上 | ❌ |
| `app.py` | 652 | 同上 | ❌ |
| `app.py` | 724-725 | `int(...)` × 2 | ❌ |
| `admin.py` | 175 | `int(request.args.get("page", 1))` | ❌ |
| `admin.py` | 360 | 同上 | ❌ |
| `admin.py` | 413 | 同上 | ❌ |
| `admin.py` | 460 | 同上 | ❌ |
| `admin.py` | 608 | 同上 | ❌ |
| `nhsa_api.py` | 45 | `int(request.args.get("limit", default))` | ❌ |
| `nhsa_browse.py` | 23 | 同上 | ❌ |
| `yp2023.py` | 99 | `_safe_int(request.args.get("page")...)` | ✅ 唯一已迁移 |

**影响**：用户访问 `?page=abc` 仍会触发 500 ValueError。

**建议**：批量替换，每处 1 行改动：
```python
# Before
page = max(int(request.args.get("page", 1) or 1), 1)
# After
from .query_utils import page_from
page = page_from(request.args)
```

---

### TD-08: app.py 过大 → ✅ 显著改善

| 指标 | 上轮 | 本轮 |
|---|---|---|
| app.py 行数 | 1115 | 917 (-18%) |
| 耗材路由 | 在 app.py 内 | 独立为 `consumables.py` (196 行) ✅ |
| NHSA 浏览 | 在 app.py 内 | 独立为 `nhsa_browse.py` ✅ |
| yp2023 | 在 app.py 内 | 独立为 `yp2023.py` ✅ |

917 行仍不算小，但核心路由已分离，结构清晰多了。

---

### TD-09: dict(zip) 模式 → ✅ 完全修复

`row_to_dict()` 在 `query_utils.py` 中实现，已被全项目采用：
- `app.py` — 3 处 ✅
- `admin.py` — 11 处 ✅
- `consumables.py` — 8 处 ✅
- `nhsa_browse.py` — 7 处 ✅

旧的 `dict(zip(keys, row))` 模式已被清除。

---

### TD-10: 静态文件缓存 → ✅ 修复

```python
# app.py:43
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0 if app.debug else 3600  # dev=0 / prod=1h
```

开发环境 0 缓存（方便调试），生产环境 1 小时缓存（提升性能）。
比原来无条件禁用缓存好得多。

---

### TD-12: row_factory 临时切换 → 🟡 未修复

`app.py:618-620, 630-644, 683` 仍有：
```python
conn.row_factory = sqlite3.Row
rows = conn.execute(sql, params).fetchall()
conn.row_factory = None
```

如果 `execute` 抛异常，`row_factory` 不会被恢复。实际影响较小
（连接在 `with db.connect()` 的 finally 中 close），但不规范。

---

### TD-13: Lint 配置 → ✅ 保持 (上轮已确认)

---

## 四、技术债清单 — 三轮对比

| # | 问题 | R1 | R2 | R3 | 变化 |
|---|---|---|---|---|---|
| TD-01 | SSH 密码 | 🔴 | 🟡 | ✅ | _wait_upload.py 删除 + AGENTS.md 修 |
| TD-02 | total_changes bug | 🔴 | ✅ | ✅ | — |
| TD-03 | except: pass | 🔴 | ✅ | ✅ | — |
| TD-04 | 编码乱码 | 🔴 | 🔴 | 🟡 | 大部分修复，5 处残留 |
| TD-05 | debug 模式 | 🔴 | 🟡 | 🟡 | 保持 (可接受) |
| TD-06 | FTS 函数重复 | 🟡 | 🟡 | 🟡🔴 | 工具建了，但引入回归 bug |
| TD-07 | int() 未验证 | 🟡 | 🟡 | 🟡 | 工具建了，12/13 未迁移 |
| TD-08 | app.py 过大 | 🟡 | 🟡 | ✅ | 拆分 consumables + nhsa_browse |
| TD-09 | dict(zip) 模式 | 🟡 | 🟡 | ✅ | row_to_dict 全项目采用 |
| TD-10 | 静态缓存 | 🟡 | 🟡 | ✅ | dev=0/prod=1h 条件化 |
| TD-11 | requirements | 🟡 | ❓ | ❓ | 未验证 |
| TD-12 | row_factory | 🟡 | 🟡 | 🟡 | 未修复 |
| TD-13 | Lint 配置 | 🟡 | ✅ | ✅ | — |

**统计**：
- ✅ 已修复：7 项 (TD-01, 02, 03, 08, 09, 10, 13)
- 🟡 部分修复：5 项 (TD-04, 05, 06, 07, 12)
- ❓ 待验证：1 项 (TD-11)
- 🔴 新发现回归：1 项 (NEW-04)

---

## 五、NEW-04: 🔴 admin.py 搜索功能 NameError (回归 bug)

**严重程度**：🔴 Blocker — 用户功能崩溃

**根因**：TD-06 重构时删除了 `_admin_fts_query` 函数定义，导入了新的
`fts_query`，但两个调用点（line 368, 613）未同步更新函数名。

**触发条件**：在管理后台任何搜索框输入关键词并提交。

**修复**：
```diff
- fts = _admin_fts_query(q)
+ fts = fts_query(q)
```
两处改动，2 分钟搞定。

---

## 六、下一步建议 (按优先级)

### 立即 (今天)

1. **🔴 修 NEW-04** — `admin.py:368` 和 `613`，`_admin_fts_query` → `fts_query`
2. **修 TD-04 残留** — `db.py` 5 处乱码注释，纯文本修改

### 本周

3. **迁移 TD-07** — 12 处 `int(request.args.get(...))` 批量替换为 `page_from()` / `limit_from()`
4. **轮换服务器密码** — `***REDACTED***` 已出现在审查文档中，虽非代码问题但建议轮换

### 适时

5. TD-12: `row_factory` 用 try/finally 包裹
6. TD-11: 验证 `requirements.txt` 包含 paramiko + gunicorn
7. TD-05: 可选改为 `FLASK_DEBUG` 环境变量控制

---

## 七、结语

三轮审查下来，进步轨迹清晰：

- **R1→R2**：修了 3 个 🔴，工具链超额落地
- **R2→R3**：修了 2 个 🔴 残留，主动推进 4 项 🟡 重构（TD-08/09/10 + query_utils）

`query_utils.py` 的设计质量值得表扬——`fts_search()` 封装了 FTS + LIKE
fallback，`_safe_int()` 带钳位，`row_to_dict()` 兼容两种 row 类型。
这不是"为了修 TD 而修"，是真正的架构提升。

唯一的遗憾是 admin.py 的函数名没改干净，导致搜索功能崩溃。
**改完 NEW-04 + TD-04 残留，这轮就收工了。**
