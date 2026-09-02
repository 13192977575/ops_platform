"""数据范围(DataScope)计算与查询过滤。

语义:
- 每条 DataScope 是 (business, project?, environment?) 三元组,project/environment 为空表示该维度全部;
- 用户可见范围 = 其所有角色 DataScope 并集 ∪ 用户自身 DataScope 并集;
- 超级管理员不受限(get_user_scopes 返回 None 表示"不限")。

过滤规则(与资产模型 business/project/environment 三字段对齐):
- (b, None, None) → business=b 的全部资产
- (b, p,   None) → business=b 且 project=p 的全部资产
- (b, None, e  ) → business=b 且 environment=e 的全部资产
- (b, p,   e  ) → business=b 且 project=p 且 environment=e 的资产
"""
from django.db.models import Q, QuerySet

from .models import DataScope


def get_user_scopes(user):
    """返回用户合并后的数据范围集合,元素为 (business_id, project_id|None, environment_id|None)。

    超级管理员返回 None(表示不限);普通用户无任何授权时返回空集合(默认拒绝一切)。
    """
    if user.is_superuser:
        return None
    scopes = DataScope.objects.filter(Q(role__users=user) | Q(user=user))
    return {
        (s.business_id, s.project_id, s.environment_id)
        for s in scopes.only("business_id", "project_id", "environment_id")
    }


def build_scope_q(
    scopes,
    business_field="business",
    project_field="project",
    environment_field="environment",
):
    """把 scope 集合转换为 queryset 过滤用的 Q 对象;None 表示不限。"""
    if scopes is None:
        return None
    q = Q(pk__isnull=True)  # 空授权集合默认拒绝所有
    for business_id, project_id, environment_id in scopes:
        kwargs = {business_field: business_id}
        if project_id is not None:
            kwargs[project_field] = project_id
        if environment_id is not None:
            kwargs[environment_field] = environment_id
        q |= Q(**kwargs)
    return q


def scope_queryset(
    qs: QuerySet,
    user,
    business_field="business",
    project_field="project",
    environment_field="environment",
) -> QuerySet:
    """对资产 queryset 应用用户数据范围过滤。"""
    scopes = get_user_scopes(user)
    q = build_scope_q(scopes, business_field, project_field, environment_field)
    return qs if q is None else qs.filter(q)


def user_can_access(user, obj) -> bool:
    """判断用户是否有权访问单个资产对象(数据范围层面)。"""
    if user.is_superuser:
        return True
    q = build_scope_q(get_user_scopes(user))
    if q is None:
        return True
    return type(obj).objects.filter(pk=obj.pk).filter(q).exists()
