# ops_platform — 运维自动化管理平台

统一管理并执行 Python 脚本、定时任务与 HTTP 接口的 Django 平台(开发中,当前完成 P0 脚手架 + P1 用户权限)。

## Project
- 后端:Django 5.2 + DRF 3.16 + SimpleJWT + Celery 5.5(Redis broker)+ django-celery-beat;Python 3.12(venv 在 `.venv`)
- 数据库:dev 用 SQLite(`db.sqlite3`),prod 用 PostgreSQL(配置必须来自环境变量)
- 入口:`manage.py`,项目配置包 `ops_platform/`,业务 app 统一放 `ops_platform/apps/*`
- 所有命令请用 `.venv\Scripts\python.exe`(Windows / PowerShell)

## Commands
- 运行测试:`python manage.py test`(可加 app 路径,如 `python manage.py test ops_platform.apps.accounts`)
- 系统检查:`python manage.py check`
- 迁移:`python manage.py makemigrations <app>` / `python manage.py migrate`
- 开发服务器:`python manage.py runserver`
- 依赖:`pip install -r requirements-dev.txt`(base/prod 见 `requirements-*.txt`)

## Architecture
- `ops_platform/settings/` — 分环境配置,`DJANGO_ENV=dev|prod` 选择,敏感配置全部走环境变量/.env,禁止硬编码
- `ops_platform/celery.py` — Celery 应用,Redis broker/result,DatabaseScheduler
- `ops_platform/apps/common/` — `BaseModel` 抽象基类(created_at/updated_at)
- `ops_platform/apps/accounts/` — User(RBAC)/Role/Business/Project/Environment/DataScope,JWT 登录(`/api/auth/login|refresh|me`),数据范围过滤与权限类
  - `accounts/scope.py` — 数据范围计算与 queryset 过滤
  - `accounts/permissions.py` — `HasPerm`(view.required_permission)+ `DataScopeFilterBackend`
- 路由:`ops_platform/urls.py` → `/api/` 下挂各 app

## Conventions
- 全部数据库访问使用 Django ORM,禁止 SQL 拼接
- 数据范围三字段固定命名 `business / project / environment`;资产模型必须继承 `BaseModel`
- 权限 codename 格式 `<action>_<resource>`(如 `execute_script`),视图用 `required_permission` 声明
- Web 请求禁止同步执行耗时脚本(一律走 Celery 异步)
- 新 app 放 `ops_platform/apps/<name>`,apps.py 中 `name = "ops_platform.apps.<name>"`
- 测试:新增功能必须带测试(`manage.py test` 使用完整模块路径)

## Notes
- 2026-09-01: P0 脚手架 + P1 用户权限已交付并通过用户验收(17 个测试全绿)。
- 2026-09-01: P2 脚本 + 执行引擎已交付(45 个测试全绿):scripts(资产/参数/版本)、
  executions(统一执行链路 + 状态机)、logs(统一日志 + 敏感过滤)、executors(本地进程执行器)、
  ops_sdk(脚本侧 SDK)。执行链路:POST /api/scripts/{id}/execute/ → Execution(pending)
  → Celery execute_asset → 本地子进程(超时/资源限制)→ 日志流式入库 → 结果回写。
  注意:测试环境无 Redis,execute 接口测试以 mock delay 投递;Worker 需 Redis 与 celery worker 进程。
- 2026-09-01: P3 定时任务已交付(68 个测试全绿):schedules(ScheduleTask + cron/interval 解析)、
  PeriodicTask 信号同步(创建/启停/表达式变更/删除)、run_schedule(并发上限控制)、
  execute_asset 支持 SCHEDULE 资产 + 失败重试(状态经 retrying)+ 连续失败/最近执行统计。
  权限命名约定 `<action>_<resource>`(view_schedule/execute_script 等)在模型 Meta.permissions 显式声明。
  PeriodicTask 无 next_run_at 字段,由 ModelEntry 计算(见 ScheduleTask.next_run_at)。
- 2026-09-01: P4 接口管理已交付(90 个测试全绿):endpoints(HttpEndpoint/EndpointCallLog)、
  expose 模式(绑定脚本暴露为 HTTP API,invoke 入口,X-API-Key 仅存哈希/JWT+execute_endpoint 双认证,
  异步执行返回 execution_id)、monitor 模式(requests 周期探测,滚动 50 次窗口健康统计:
  healthy/degraded/down,错误率阈值 0.2)、execute_asset 支持 ENDPOINT 并回写调用记录与健康统计。
  monitor 巡检任务 monitor-endpoints(60s interval)由 post_migrate 自动注册。
- 2026-09-01: P5 日志中心 + 审计已交付(105 个测试全绿):logs 检索 API(/api/logs/,
  时间范围/任务/用户/级别/关键字,数据范围过滤)、日志保留清理(clean-old-logs 每日 03:00,
  LOG_RETENTION_DAYS 默认 90);audit app(AuditLog 仅追加,模型层禁改删,登录/资产增删改
  启停/执行/invoke 埋点,AuditMixin 统一埋点,/api/audit-logs/ 查询)。
  修复 P2 遗留缺陷:CreateScriptSerializer 的 code 字段被初始代码占用导致脚本编码落空,
  初始代码改为 source_code 字段。注意:logs 检索 created_after 等参数需经客户端 URL 编码
  (isoformat 含 + 号)。
  下一步:P6 监控告警(alerts)。
- 2026-09-01: P6 监控告警已交付(123 个测试全绿):alerts app——渠道(企微/钉钉/邮件/Webhook,
  敏感凭据 Fernet 加密存储,读取脱敏 ***,密钥 ALERT_ENCRYPTION_KEY dev 固定默认/prod 强制)、
  规则(连续失败/超时/接口不可用/响应慢,阈值+级别+静默窗口)、评估器(evaluate_execution 挂
  execute_asset 执行后、evaluate_endpoint 挂 monitor 巡检后)、静默收敛(SILENCED 防风暴)、
  记录(发送结果/确认 ack)。API:/api/alert-channels|alert-rules|alert-records(规则按数据范围)。
  下一步:P7 执行器扩展(Docker 隔离/多节点 Agent)+ 资源限制细化。
- 2026-09-01: P7 执行器扩展已交付(130 个测试全绿):DockerExecutor(runner=docker:image[:tag],
  docker run --rm 挂载执行,资源限制 -m/--cpus,超时 docker kill 清理容器,流式日志);
  Script 新增 memory_limit_mb/cpu_limit 字段;本地执行器 POSIX 用 preexec_fn 应用 RLIMIT_AS
  (Windows 跳过,CPU 限制仅 Docker 生效);注册表解析 docker:→Docker、agent:→明确报错(二期)。
  Docker 真实执行需本机安装 docker,测试以 mock docker CLI 验证命令构造。
  下一步:P8 测试补全与上线部署(docker-compose/部署文档/接口测试补全)。
- 2026-09-01: P8 测试补全与上线部署已交付(132 个测试全绿):health 探活接口(/api/health/,
  免认证)+ 冒烟测试;Dockerfile(gunicorn 4 worker)+ docker-compose.yml(PostgreSQL/Redis/
  Web/Worker/Beat 编排,web 启动自动 migrate);.env.production.example 生产变量模板;
  DEPLOYMENT.md 部署指南(初始化/变量清单/升级排障);README 部署章节。
  注意:Docker 编排未在本机实际运行(无 docker),需在有 docker 的服务器验证。
  后续建议:多节点 Agent 执行器(二期)、执行产物存储(MinIO/S3)、接口代理转发(二期)。
- 2026-09-02: 增强交付(135 个测试全绿):
  ① 前端 SimpleUI(中文美化 admin + 自定义菜单分组 + /dashboard/ 仪表盘统计页);
  ② 脚本文件集 files(多文件+子目录,执行时写入临时目录,可 import;防路径穿越)
     + 环境变量 env_vars(敏感键 Fernet 加密落库,读取只回显 ***,执行注入 os.environ,
     修改即时生效无需重建版本;文件集内可含 .env 由脚本 python-dotenv 加载);
     加密工具通用化到 common.crypto(alerts 复用);
  ③ 第三方库:全局安装在 worker 容器 Python 环境(DEPLOYMENT.md 第 8 节),隔离用 Docker runner。
  部署同步注意:新增 django-simpleui 依赖需 docker compose build;scripts 迁移 0004。
