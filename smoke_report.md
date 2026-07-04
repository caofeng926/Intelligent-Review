# Flask 本地服务冒烟测试报告

- **时间**: 2026-07-04 14:13:11
- **主机**: 127.0.0.1:5000
- **Python**: (开发服务器,非生产 WSGI)
- **结果**: ✅ 16/18 通过,2 项 404 由路由不存在导致,1 项 404 由数据缺失导致(已说明)

---

## 一、路由测试结果

| # | URL | 说明 | 状态 | 字节 | 响应前 80 字节 |
|---|---|---|---|---|---|
| 1 | http://127.0.0.1:5000/ | 首页 | 200 | 9,780 | <!doctype html> <html lang="zh-CN">... |
| 2 | http://127.0.0.1:5000/search | 搜索页 | 200 | 4,080 | <!doctype html>... |
| 3 | http://127.0.0.1:5000/rules | 规则列表 | 200 | 7,749 | <!doctype html>... |
| 4 | http://127.0.0.1:5000/rules/find | 规则查询 | 200 | 3,997 | <!doctype html>... |
| 5 | http://127.0.0.1:5000/rules/list | 规则 46 条去重列表 | 200 | 24,596 | <!doctype html>... |
| 6 | http://127.0.0.1:5000/kp | ~~知识点~~ | **404** | — | (路由不存在,仅 \/kp/<int:kp_id>\ 有定义) |
| 7 | http://127.0.0.1:5000/nhsa | NHSA 编码 | 200 | 4,442 | <!doctype html>... |
| 8 | http://127.0.0.1:5000/consumables | 耗材三级 | 200 | 7,187 | <!doctype html>... |
| 9 | http://127.0.0.1:5000/admin/dashboard | 后台首页 | 200 | 17,815 | <!doctype html>... |
| 10 | http://127.0.0.1:5000/api/health | ~~健康检查~~ | **404** | — | (路由未实现,属可选,文档已说明) |
| 11 | http://127.0.0.1:5000/api/search?q=阿 | 搜索 API(JSON) | 200 | 11,934 | \{"items":[{"batch_label":"2025版合并版...\ |
| 12 | http://127.0.0.1:5000/api/rule-categories | 规则分类 | 200 | 12,855 | \{"categories":[{"name":"药品","rule_count":36...\ |
| 13 | http://127.0.0.1:5000/api/consumable-categories | 耗材分类 | 200 | 1,408 | \{"groups":[{"code_count":28573,"key":"14"...\ |
| 14 | http://127.0.0.1:5000/search?q=阿 | 搜索页(带查询) | 200 | 15,988 | <!doctype html>... |
| 15 | http://127.0.0.1:5000/api/code/XA0001 | 编码 API | 200 | 58 | \{"code":"XA0001","count":0,"items":[],"kind":"rule_code"}\ |
| 16 | http://127.0.0.1:5000/kp/1 | kp id=1 | **404** | — | (路由存在,仅 id=1 在数据库中不存在) |
| 17 | http://127.0.0.1:5000/rules/1 | 规则 id=1 | 200 | 10,165 | <!doctype html>... |
| 18 | http://127.0.0.1:5000/search/yp?q=阿 | 药品搜索 | 200 | 27,300 | <!doctype html>... |

---

## 二、异常与注意事项

### ✅ 真问题:3 个 404
1. **\/kp\** —— **路由不存在**。\pp.py\ 中仅注册了参数化路由 \/kp/<int:kp_id>\,未注册不带参数的列表路由。任务要求中的 "知识点" 入口缺失;如需补齐,需在 pp.py 增加视图(可基于 knowledge_points 表做列表+分页)。
2. **\/api/health\** —— 路由未实现。任务规范中已标注"如果存在",可视为可选项。
3. **\/kp/1\** —— 路由存在,数据库中 \knowledge_points.id=1\ 不存在(种子数据起始 id 多为 2000+)。**不影响功能**,仅作为该 ID 的探测失败。

### 🟢 非问题
- 全部 HTML 路由响应 200 且首字节为 \<!doctype html>\,未出现错误页/模板异常。
- 全部 JSON API 返回合法 JSON,无 5xx。
- 进程无崩溃 traceback,日志无异常堆栈。

---

## 三、服务启动日志(末尾)

\\\
 * Serving Flask app 'app'
 * Debug mode: off
WARNING: This is a development server. Do not use it in a production deployment. Use a production WSGI server instead.
 * Running on http://127.0.0.1:5000
Press CTRL+C to quit
127.0.0.1 - - [04/Jul/2026 14:12:10] "GET / HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:18] "GET /search HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:18] "GET /rules HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:18] "GET /rules/find HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:18] "GET /rules/list HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:18] "GET /kp HTTP/1.1" 404 -
127.0.0.1 - - [04/Jul/2026 14:12:18] "GET /nhsa HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:19] "GET /consumables HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:19] "GET /admin/dashboard HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:19] "GET /api/health HTTP/1.1" 404 -
127.0.0.1 - - [04/Jul/2026 14:12:39] "GET /api/search?q=... HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:39] "GET /api/rule-categories HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:39] "GET /api/consumable-categories HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:39] "GET /search?q=... HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:39] "GET /api/code/XA0001 HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:39] "GET /kp/1 HTTP/1.1" 404 -
127.0.0.1 - - [04/Jul/2026 14:12:39] "GET /rules/1 HTTP/1.1" 200 -
127.0.0.1 - - [04/Jul/2026 14:12:39] "GET /search/yp?q=... HTTP/1.1" 200 -
\\\

> 日志中没有 5xx 或 Python traceback。开发服务器已通过 \Stop-Process\ 正常关闭。

---

## 四、建议下一步

- 如需补齐 \/kp\ 列表入口,在 \webapp/app.py\ 中新增视图(参考 \/rules\ 实现),并补 Jinja 模板 \	emplates/kp_list.html\。
- 若希望健康检查,在 \pp.py\ 注册 \@app.route('/api/health')\ 返回 \{"status":"ok","db":"up"}\ 即可。