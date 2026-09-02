"""ops_platform 项目包。

注意:不要在包级导入 celery(避免 manage.py populate 阶段加载 celery.py
触发 django.setup() 重入);celery 应用通过 `celery -A ops_platform.celery` 使用。
"""
