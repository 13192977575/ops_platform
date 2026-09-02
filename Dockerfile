# ops_platform 生产镜像
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_ENV=prod

WORKDIR /app

# 先装依赖(利用构建缓存);prod 引用 base,两个文件都要 COPY
COPY requirements-base.txt requirements-prod.txt ./
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "ops_platform.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "60"]
