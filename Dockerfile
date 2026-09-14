# ops_platform 生产镜像
# 明确使用 Debian 12，便于安装 Microsoft ODBC Driver 18(SQL Server 脚本依赖)。
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_ENV=prod

WORKDIR /app

# pyodbc 通过 unixODBC 调用系统驱动；Microsoft ODBC Driver 必须在 worker
# 容器中存在。所有服务共用本镜像，因此 Web/Worker/Beat 的依赖保持一致。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        unixodbc-dev \
    && curl -sSL -o /tmp/packages-microsoft-prod.deb \
        https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && rm /tmp/packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖(利用构建缓存);prod 引用 base,两个文件都要 COPY
COPY requirements-base.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "ops_platform.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "60"]
