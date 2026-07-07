# 第四轮代码审查报告

> 审查日期：2026-07-06 (第四轮)
> 审查目的：验证 R3 修复进展 + 新代码质量
> 对照标准：CODE_REVIEW.md v1.0 + R2/R3 技术债清单

---

## 一、总体评价

**架构重构做得非常好。** app.py 从 R1 的 1115 行一路缩减到 372 行，
拆出 `kp.py`、`rules.py`、`search_backend.py`、`helpers.py` 四个模块，
模块边界清晰，`register(app)` 模式统一。`query_utils.py` 的工具函数
设计扎实，`search_backend.py` 的搜索逻辑分离干净。

**但 R3 报告的 🔴 回归 bug (NEW-04) 仍未修复**——admin.py 搜索功能
依然会 NameError 崩溃。同时，新一轮重构引入了新的代码重复：
`detect_mode()` 和 `_code_search()` 各被重新实现了一遍，而 `query_utils`
里已有现成的工具函数。

---

## 二、🔴 Blocker 复审

### NEW-04: admin.py 搜索 NameError → ❌ 仍未修复 (第三轮至今)

```python
# admin.py:19 — 导入了新函数，但从未使用
from .query_utils import fts_query       # 死导入

# admin.py:368 — 仍调用已删除的旧函数
fts = _admin_fts_query(q)                # ❌ NameError

# admin.py:613 — 同样
fts = _admin_fts_query(q)                # ❌ NameError
```

**影响**：管理后台所有搜索功能（代码表搜索 + 知识点搜索）提交关键词后
立即 500 崩溃。已持续两轮审查未修。

**修复**（2 行）：
```diff
- fts = _admin_fts_query(q)
+ fts = fts_query(q)
```

---

### TD-04: db.py 编码乱码 → ❌ 仍未修复 (第一轮至今)

5 处乱码注释原封不动：

| 行号 | 当前乱码 | 应为 |
|---|---|---|
| 60 | `对应知识点序号?.` | `对应知识点序号)` |
| 96 | `医用耗材代码库?(from NHSA...` | `医用耗材代码库（from NHSA...` |
| 354 | `(銆?` | `（、）` |
| 524 | `閸忋劌娴楅崠鑖ゆ灍閺堝秴濮熸い鍦窗` | `医疗服务项目代码库` |
| 569 | `娑撹弓鑵戦崠鑖ゆ⒕/鐠囦椒绶?2.0 閻楋拷` | `中药饮片/民族药 2.0 版` |

纯注释修改，零风险。已持续四轮。

---

## 三、🟡 项复审 — 重构进展与回归

### TD-08: app.py 过大 → ✅ 大幅改善 (本轮最大亮点)

| 指标 | R1 | R3 | R4 | 变化 |
|---|---|---|---|---|
| app.py 行数 | 1115 | 917 | **372** | -67% |
| 模块数 | 1 | 4 | **8** | kp/rules/search_backend/helpers 新增 |

新提取模块：
- `kp.py` (115 行) — KP 详情页 + API
- `rules.py` (355 行) — 规则浏览/分类/查找
- `search_backend.py` (162 行) — 搜索逻辑 (detect_mode + 3 种搜索)
- `helpers.py` (52 行) — 共享常量 + `parse_kp_partner`

`register(app)` 模式统一，模块边界清晰。**架构质量很高。**

---

### TD-06: FTS/搜索函数重复 → 🟡 工具建了，但新重复又冒出来

**已统一的** ✅：
- `app.py` / `search_backend.py` / `kp.py` 都用 `query_utils.fts_query`
- `rules.py:266` 用 `jieba_query(q)` 构造 FTS 表达式

**仍未统一的** ❌：

**1. NEW-04 (admin.py)** — 仍在调用不存在的 `_admin_fts_query`（见上）

**2. NEW-05: rules.py 重新实现了 `detect_mode()`**

```python
# rules.py:231-244 — 完整复制了 search_backend.py:25-35 的函数
def detect_mode(q: str) -> str:
    """根据查询字符串判断搜索模式。"""
    import re                              # ❌ 每次调用都 import
    code_re = re.compile(r"^[A-Z0-9]{8,}$")  # ❌ 每次调用都编译正则
    letters_re = re.compile(r"^[A-Za-z]+$")
    ...
```

对比 `search_backend.py:21-35`：
```python
CODE_RE = re.compile(r"^[A-Z0-9]{8,}$")     # ✅ 模块级编译一次
LETTERS_RE = re.compile(r"^[A-Za-z]+$")

def detect_mode(q: str) -> str:             # ✅ 函数内不重复编译
    ...
```

`rules.py` 没有从 `search_backend` 导入 `detect_mode`，而是自己写了一份，
还把 `import re` 和 `re.compile` 放进了函数体内——每次搜索都重新编译正则。

**修复**：删除 `rules.py:231-244`，改为 `from .search_backend import detect_mode`。

**3. NEW-06: app.py `_code_search()` 重复了 `query_utils.fts_search()`**

`query_utils.py` 专门创建了 `fts_search()` 函数（FTS5 + LIKE fallback），
但 `app.py:184-218` 又写了一个几乎相同的 `_code_search()`：

```python
# app.py:192 — 直接用 q + "*"，绕过了 fts_query() 的 ASCII/中文分支
fts = q + "*"
```

`fts_query()` 会根据纯 ASCII vs 中文走不同策略（ASCII 加 `*`，中文取前
2 字符做 `"xx"*` 前缀匹配），而 `app.py:192` 对所有输入统一 `q + "*"`——
中文短语搜索可能匹配不到结果。

**4. NEW-07: app.py:192 绕过 fts_query() 的中文处理**

同上。`q + "*"` 对中文长词（如"阿莫西林胶囊"）生成的 FTS 表达式是
`阿莫西林胶囊*`，而 `fts_query()` 会生成 `"阿莫"*`（取前 2 字符做前缀
匹配），后者命中率更高。

---

### TD-07: int() 未验证 → 🟡 工具建了，14 处未迁移

`query_utils.page_from()` / `limit_from()` / `_safe_int()` 已就绪。
`rules.py:170` 正确使用了 `_safe_int()` ✅。

**但其余 14 处仍用裸 `int()`**：

| 文件 | 行号 | 代码 |
|---|---|---|
| `app.py` | 107 | `int(request.args.get("page", 1) or 1)` |
| `app.py` | 253 | 同上 |
| `kp.py` | 62-63 | `int(...)` × 2 |
| `admin.py` | 175, 360, 413, 460, 608 | `int(request.args.get("page", 1))` × 5 |
| `nhsa_api.py` | 45 | `int(request.args.get("limit", default))` |
| `nhsa_browse.py` | 23 | 同上 |
| `yp2023.py` | 21, 98 | `int(...)` × 2 |

用户访问 `?page=abc` → 500 ValueError。

---

### TD-09: dict(zip) 模式 → ✅ 保持修复

`row_to_dict()` 全项目持续使用。

---

### TD-10: 静态缓存 → ✅ 保持修复

`app.py:44`: `0 if app.debug else 3600`

---

### TD-12: row_factory 临时切换 → 🟡 未修复，新增 2 处

| 位置 | 模式 |
|---|---|
| `app.py` (R3 报告) | set → execute → reset |
| `rules.py:286-288` | `conn.row_factory = sqlite3.Row` → execute → `conn.row_factory = None` |
| `rules.py:337-351` | 同上 |

如果 `execute` 抛异常，`row_factory` 不会恢复。实际影响小（连接在
`with` 中 close），但不规范。

---

## 四、技术债清单 — 四轮对比

| # | 问题 | R1 | R2 | R3 | R4 | 趋势 |
|---|---|---|---|---|---|---|
| TD-01 | SSH 密码 | 🔴 | 🟡 | ✅ | ✅ | — |
| TD-02 | total_changes bug | 🔴 | ✅ | ✅ | ✅ | — |
| TD-03 | except: pass | 🔴 | ✅ | ✅ | ✅ | — |
| TD-04 | 编码乱码 | 🔴 | 🔴 | 🟡 | 🟡 | ⚠️ 停滞 4 轮 |
| TD-05 | debug 模式 | 🔴 | 🟡 | 🟡 | 🟡 | 可接受 |
| TD-06 | FTS 函数重复 | 🟡 | 🟡 | 🟡 | 🟡 | ⚠️ 新重复冒出 |
| TD-07 | int() 未验证 | 🟡 | 🟡 | 🟡 | 🟡 | ⚠️ 停滞 3 轮 |
| TD-08 | app.py 过大 | 🟡 | 🟡 | ✅ | ✅ | 🎉 持续改善 |
| TD-09 | dict(zip) 模式 | 🟡 | 🟡 | ✅ | ✅ | — |
| TD-10 | 静态缓存 | 🟡 | 🟡 | ✅ | ✅ | — |
| TD-11 | requirements | 🟡 | ❓ | ❓ | ❓ | 未验证 |
| TD-12 | row_factory | 🟡 | 🟡 | 🟡 | 🟡 | ⚠️ 新增 2 处 |
| TD-13 | Lint 配置 | 🟡 | ✅ | ✅ | ✅ | — |
| NEW-04 | admin NameError | — | — | 🔴 | 🔴 | ⚠️ 停滞 2 轮 |
| NEW-05 | detect_mode 重复 | — | — | — | 🟡 | 新发现 |
| NEW-06 | _code_search 重复 | — | — | — | 🟡 | 新发现 |
| NEW-07 | 绕过 fts_query 中文处理 | — | — | — | 🟡 | 新发现 |

**统计**：
- ✅ 已修复：7 项
- 🟡 部分修复/未修复：8 项
- 🔴 Blocker：2 项 (NEW-04 + TD-04)
- ❓ 待验证：1 项

---

## 五、值得表扬的代码

### ✅ `search_backend.py` — 搜索逻辑分离干净

三种搜索模式（name/initials/code）各自独立函数，`do_search()` 统一派发，
`_row_to_kp_dict()` 正确处理了 partner 解析。`search_initials()` 末尾
追加 `None` 保持元组格式一致——这个细节很专业。

### ✅ `rules.py` — 规则分类设计好

`_categorize_subject()` + `CATEGORY_PREFIXES` 用前缀匹配做分类，覆盖
了 47 条规则的所有主题。`/rules/find` 的按规则分组搜索逻辑清晰，
NHSA 优先排序合理。

### ✅ `helpers.py` — 单一数据源

`SOURCE_LABEL` 和 `PAGE_SIZE` 集中管理，注释说明了"Kept in sync
between app.py and kp.py via this single source of truth"——有意识
地避免重复。

### ✅ `qa.py` — QA 脚本质量好

`norm()` 剥离实体前缀做模糊匹配，`difflib.SequenceMatcher` 做相似度
打分，verdict 有明确的 pass/fail 判定。结构化输出 JSON 报告，方便
自动化。`__import__("datetime")` 略显非常规但无功能问题。

---

## 六、下一步建议 (按优先级)

### 立即 (10 分钟)

1. **🔴 修 NEW-04** — `admin.py:368,613`，`_admin_fts_query` → `fts_query`
2. **修 TD-04** — `db.py` 5 处乱码注释

### 本周 (1 小时)

3. **修 NEW-05** — 删 `rules.py:231-244` 的 `detect_mode()`，改为从
   `search_backend` 导入
4. **修 NEW-06+07** — `app.py:_code_search()` 改用 `query_utils.fts_search()`，
   或至少把 `q + "*"` 换成 `fts_query(q)`
5. **迁移 TD-07** — 14 处 `int(request.args.get(...))` → `page_from()` / `limit_from()`

### 适时

6. TD-12: `row_factory` 用 try/finally 包裹
7. TD-11: 验证 `requirements.txt`

---

## 七、结语

四轮审查下来，趋势很清楚：

- **架构能力很强** — app.py 从 1115→372 行，8 个模块边界清晰
- **工具建设到位** — query_utils / search_backend / helpers 设计扎实
- **但"最后一公里"反复掉链子** — NEW-04 两行改动拖了两轮，TD-04 五行
  注释拖了四轮，TD-07 工具建了但调用点不迁移

这像是造了一条很好的高速公路，但匝道口忘了修连接线。建议把 NEW-04
和 TD-04 当作"今日必做"——它们加起来不到 10 行改动，却是仅剩的两个
🔴 blocker。修完之后，代码质量就真正配得上架构水平了。
