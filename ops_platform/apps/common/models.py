"""平台公共模型基类。"""
from django.db import models


class BaseModel(models.Model):
    """所有业务模型的公共字段:创建/更新时间。"""

    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        abstract = True
