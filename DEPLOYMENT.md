# 部署指南(生产环境)

ops_platform 生产部署采用 docker compose 编排:PostgreSQL(主库)+ Redis(broker/缓存)+ Web(gunicorn)+ Worker(Celery)+ Beat(调度器)。

## 1. 前置要求

- 服务器装有 Docker 与 Docker Compose V2
- 域名解析到服务器(或直接用 IP,配置 `DJANGO_ALLOWED_HOSTS`)

## 2. 初始化

```bash
# 生成密钥
python -c "import secrets; print(secrets.token_urlsafe(50))"        # DJANGO_SECRET_KEY
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # ALERT_ENCRYPTION_KEY

cp .env.production.example .env.production
# 编辑 .env.production 填入密钥/密码/域名/SMTP

docker compose build
docker compose up -d
```

`web` 服务启动时自动执行 `migrate`。

## 3. 首次初始化数据

```bash
# 创建超级管理员(在 web 容器内)
docker compose exec web python manage.py createsuperuser

# (可选)初始化业务线/项目/环境/角色/权限
# 建议通过 admin 后台 /api 完成:http://<host>:8000/admin/
```

## 4. 环境变量清单

| 变量 | 必填 | 说明 |
|------|------|------|
| `DJANGO_ENV` | 是 | 固定 `prod` |
| `DJANGO_SECRET_KEY` | 是 | 随机 50 字符,缺失即启动失败 |
| `DJANGO_ALLOWED_HOSTS` | 是 | 逗号分隔域名;禁止 `*`(启动校验) |
| `POSTGRES_*` | 是 | 数据库连接;`POSTGRES_HOST=db`(compose 服务名) |
| `REDIS_URL` | 是 | `redis://redis:6379/0` |
| `ALERT_ENCRYPTION_KEY` | 是 | Fernet 密钥,缺失即启动失败 |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_DAYS` | 否 | 令牌有效期 |
| `LOG_RETENTION_DAYS` | 否 | 日志保留天数(默认 90) |
| `EMAIL_*` | 渠道用 | SMTP 告警邮件 |
| `CSRF_COOKIE_SECURE` 等 | 否 | HTTPS 加固 |

## 5. 服务说明

- **web**:gunicorn 4 worker,`/api/health/` 供探活
- **worker**:消费执行任务(脚本/定时/接口调用),`--concurrency=4` 可按需调整
- **beat**:DatabaseScheduler,驱动定时任务与周期任务(monitor 巡检、日志清理、每日清理)
- **db / redis**:数据与消息队列

## 6. 升级与回滚

```bash
git pull
docker compose build
docker compose up -d          # web 启动时自动 migrate + collectstatic
docker compose exec web python manage.py check --deploy   # 可选:部署安全检查
```

## 7. 数据持久化与参数修改

**已持久化(容器重建不丢失):**
- 数据库全部业务数据(资产/任务/接口/执行记录/日志/审计/告警/调度状态)→ PostgreSQL 卷 `pgdata`
- 平台内可改的配置(告警渠道与规则、权限、角色)都在数据库,通过 admin/API 修改,**无需重启容器**

**通过环境变量修改(需重建生效):**
- SMTP、JWT 有效期、日志保留天数等 → 改 `.env.production` 后 `docker compose up -d`

**无需持久化/映射:**
- 应用日志:统一走容器 stdout,用 `docker compose logs -f web` 查看(平台内的执行日志在数据库中,不受影响)
- 脚本执行临时目录:由执行器自动创建与清理

## 8. 安装第三方库(脚本依赖)

执行器使用 **worker 容器的 Python 环境**,所有脚本/定时任务/接口调用**共享**该环境——装一次全体生效。

```bash
# ① 在 requirements-base.txt 增加依赖(如 pandas==2.2.3),然后:
docker compose build && docker compose up -d

# ② 临时验证(仅当前容器,重建/重部署会丢,慎用)
docker compose exec worker pip install pandas
```

**隔离场景建议:**
- 某个脚本需要**特殊版本或大量依赖**,不想污染主环境 → 用 **Docker 执行器**:`runner=docker:python:3.12-pandas`(镜像自带依赖,天然隔离)
- 计划支持脚本级 `requirements` + 独立 venv(二期)

## 9. 常见问题

- **告警收不到**:确认 `ALERT_ENCRYPTION_KEY` 与创建渠道时一致(密钥变更会导致加密配置无法解密)。
- **定时任务未触发**:确认 `beat` 服务在运行,且 `django_celery_beat` 表有 `PeriodicTask`(创建任务时自动生成)。
- **执行失败 "docker 未找到"**:Docker 执行器需 worker 所在主机有 docker 且用户有执行权限。
- **日志过大**:调低 `LOG_RETENTION_DAYS`;清理任务每日 03:00 运行。
