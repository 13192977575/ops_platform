# ops_platform — 运维自动化管理平台

统一管理并执行 **Python 脚本、定时任务、HTTP 接口** 的 Django 平台:资产登记 → 异步调度(Celery)→ 隔离执行 → 统一日志/审计/告警。

> 当前进度:P0 脚手架 + P1 用户权限(见 [开发计划](#开发计划))。

## 技术栈

- Python 3.12 / Django 5.2 / DRF 3.16 / SimpleJWT(JWT 认证)
- Celery 5.5 + Redis(broker/result/cache)+ django-celery-beat(调度)
- 数据库:开发 SQLite,生产 PostgreSQL(配置走环境变量)

## 快速开始(开发环境)

```powershell
cd E:\resonix\op
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
# 复制 .env.example 为 .env 并按需修改
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

- 后台管理:`http://127.0.0.1:8000/admin/`(需先 `createsuperuser`)
- API:`http://127.0.0.1:8000/api/auth/login/`、`/api/auth/refresh/`、`/api/auth/me/`
- 定时调度(后续阶段):`.\.venv\Scripts\celery.exe -A ops_platform worker -l info -B`

## 脚本进阶用法

**文件集(多文件 + import)**:脚本可携带多个附加文件(支持子目录),执行时写入同一目录,主代码可 `import` 它们。

```json
{
  "source_code": "from utils.db import get_conn\nprint(get_conn())",
  "files": [{"path": "utils/db.py", "content": "def get_conn():\n    return 'conn'"}, {"path": ".env", "content": "DEBUG=1"}]
}
```

**环境变量(敏感信息加密存储)**:`env_vars` 键值对在平台上**加密落库**(复用 Fernet),执行时注入 `os.environ`,脚本 `os.getenv("DB_HOST")` 直接读;读取接口只回显键名(`***`)。修改后无需重建版本,下次执行即生效。

```json
{"env_vars": {"DB_HOST": "10.0.0.5", "DB_PASSWORD": "secret"}}
```

**第三方库**:装一次全局生效(worker 的 Python 环境),见 [DEPLOYMENT.md](DEPLOYMENT.md#8-安装第三方库脚本依赖);隔离需求用 Docker 执行器。

## 生产部署(Docker)

```bash
cp .env.production.example .env.production   # 填写密钥/密码/域名
docker compose build && docker compose up -d
docker compose exec web python manage.py createsuperuser
```

编排包含:PostgreSQL、Redis、Web(gunicorn)、Celery Worker、Celery Beat。
健康探活:`GET /api/health/`。详见 [DEPLOYMENT.md](DEPLOYMENT.md)(环境变量清单、升级与排障)。

## 测试

```powershell
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py check
```

## 项目结构

```
ops_platform/
├── settings/          # 分环境配置(base/dev/prod),DJANGO_ENV 切换
├── celery.py          # Celery 应用(Redis broker,DatabaseScheduler)
├── urls.py            # 路由(/api/ 挂载各 app)
└── apps/
    ├── common/        # BaseModel 抽象基类
    └── accounts/      # 用户/角色/权限/数据范围,JWT 登录
```

## 权限模型

- **操作权限(RBAC)**:Role → Permission(`<action>_<resource>` codename,如 `execute_script`)
- **数据范围**:Business(业务线)→ Project(项目)→ Environment(环境);DataScope 授予角色/用户对 (业务×项目×环境) 组合的访问权,project/environment 为空表示全部
- 视图用 `required_permission` 声明权限,资产 queryset 经 `DataScopeFilterBackend` 自动过滤

## 安全约定

- 禁止 SQL 拼接,一律 Django ORM;所有输入参数校验
- 敏感配置(SECRET_KEY/数据库/告警凭据)只允许环境变量注入,禁止硬编码
- Web 请求禁止同步执行耗时脚本,一律 Celery 异步
- 执行脚本强制超时/资源限制/隔离(后续阶段实现)

## 开发计划

| 阶段 | 内容 | 状态 |
|------|------|------|
| P0 | 脚手架:分环境配置/DRF/JWT/Celery/common | ✅ |
| P1 | 用户权限:RBAC + 数据范围 + JWT 登录 | ✅ |
| P2 | 脚本 + 执行引擎:scripts/executions/executors/ops_sdk | ✅ |
| P3 | 定时任务:schedules + Beat 调度 | ✅ |
| P4 | 接口管理:endpoints | ✅ |
| P5 | 日志中心 + 审计 | ✅ |
| P6 | 监控告警:alerts | ✅ |
| P7 | 执行器扩展:Docker 隔离/多节点 | ✅ |
| P8 | 测试补全与上线部署 | ✅ |

## 路线图后续(二期)

- Agent 多节点执行器分发
- 执行产物存储(MinIO/S3)
- 接口代理转发(proxy 模式)
- 日志量级扩展(ELK)

详见 `AGENTS.md`(agent 工作记忆)。
