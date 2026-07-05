# 代码审查标准与流程 — 成果概览

## 完成内容

### 1. 代码质量审查报告 (嵌入 CODE_REVIEW.md §7)
对项目进行了全面代码审查，发现 **19 项技术债**，按优先级分级：
- 🔴 立即处理: 5 项 (SSH 密码泄露、total_changes 统计 bug、裸 except:pass、编码乱码、debug 模式风险)
- 🟡 近期处理: 8 项 (代码重复、输入验证、app.py 过大、缓存禁用等)
- 💭 适时处理: 6 项 (临时脚本清理、.bak 残留、无测试等)

### 2. 代码审查标准 (CODE_REVIEW.md §3)
覆盖 6 个维度共 22 条规则：
| 维度 | 规则数 | 关键项 |
|---|---|---|
| 安全性 | 5 条 | 凭据零硬编码、SQL 参数化、输入验证、debug 控制、XSS 防护 |
| 正确性 | 4 条 | 禁止静默吞错、rowcount vs total_changes、上下文管理器一致性 |
| 可维护性 | 5 条 | 消除重复、函数/文件长度上限、命名规范、docstring、编码一致性 |
| 性能 | 4 条 | 禁止 N+1、静态缓存、PRAGMA、FTS5 限制 |
| 前端 | 4 条 | 设计令牌、SVG 图标、事件委托、fetch 错误处理 |
| 数据库 | 4 条 | Schema 变更流程、索引覆盖、事务边界、FTS5 同步 |

### 3. 审查流程 (CODE_REVIEW.md §1-2, §5)
- 完整流程: 自检 → pre-commit → PR → 自动化 CI → 人工审查 → 合并
- 提交前自检清单 (通用 + Python + 前端)
- 审查者指南 (审查顺序、评论规范、该做/不该做的事)
- PR 规模指导 (400 行/次，60 分钟/次，48h 响应)

### 4. 自动化工具链 (已落地配置文件)
| 文件 | 作用 |
|---|---|
| `.flake8` | Python 语法/风格检查配置 |
| `pyproject.toml` | isort 导入排序配置 |
| `.pre-commit-config.yaml` | Git 提交前自动检查 (flake8 + isort + 密钥检测 + .bak 拦截 + 密码检测) |
| `requirements-dev.txt` | 开发依赖包 |
| `.github/workflows/code-review.yml` | GitHub Actions CI (PR 时自动 lint + 密钥扫描 + 文件卫生检查) |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR 模板 (自检清单 + 变更说明) |

## 关键发现摘要

**最严重问题** — SSH 密码 `***REDACTED***` 在 4 个文件中以明文出现，建议立即轮换并迁移到环境变量/SSH Key。

**最隐蔽 Bug** — `clean_drug_detail.py` 使用 `connection.total_changes` 统计行数，该属性返回的是连接生命周期内的累计值，导致所有统计数字都是错的。应改用 `cursor.rowcount`。

**最大可维护性风险** — 无 lint/format/test 配置 + 87 个临时脚本 + app.py 1111 行，建议优先建立自动化工具链。

## 后续建议

1. **立即执行**: 轮换 SSH 密码，移除硬编码凭据
2. **本周内**: 安装 pre-commit (`pip install -r requirements-dev.txt && pre-commit install`)
3. **逐步推进**: 按技术债清单优先级修复 🔴 项
