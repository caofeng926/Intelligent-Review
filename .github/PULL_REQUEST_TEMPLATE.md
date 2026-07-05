## 变更说明

<!-- 一句话说明本 PR 做了什么 -->

## 变更类型

- [ ] feat: 新功能
- [ ] fix: 修复 Bug
- [ ] refactor: 重构 (不改变功能)
- [ ] perf: 性能优化
- [ ] docs: 文档更新
- [ ] chore: 杂项 / 依赖更新

## 影响范围

<!-- 列出受影响的模块/表/路由，例如: webapp/app.py, drug_detail 表, /api/search -->

## 测试方式

<!-- 描述如何验证本次变更，例如: -->
<!-- 1. 启动服务: python -m webapp.app -->
<!-- 2. 访问 /search?q=阿莫西林 确认结果正常 -->

## 自检清单

- [ ] 无硬编码凭据 (密码/密钥/SSH)
- [ ] 无裸 `except: pass` 或 `except:`
- [ ] 用户输入 (`request.args`) 已验证后类型转换
- [ ] SQL 值使用 `?` 参数化
- [ ] f-string 拼接的表名/列名来自内部常量白名单
- [ ] 新增函数有 docstring
- [ ] 无超过 10 行的代码重复
- [ ] 无 `.bak` 备份文件残留
- [ ] 无 `print()` 调试语句 (入库脚本除外)
- [ ] 无硬编码绝对路径 (`C:\Users\...`, `/opt/...`)
- [ ] 前端动态 HTML 已转义 (escapeHtml / textContent)
- [ ] CSS 使用 `--c-*` 设计令牌，无硬编码颜色

## 截图 / 输出 (如适用)

<!-- 前端变更附截图，API 变更附 curl 示例 -->

## 关联 Issue (如适用)

<!-- Closes #123 -->
