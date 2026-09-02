"""accounts 序列化器:登录(JWT)与用户信息。"""
from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class LoginSerializer(TokenObtainPairSerializer):
    """登录:返回 access/refresh 令牌,并附带用户基本信息(减少一次 /me 请求)。"""

    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        data["user"] = {
            "id": user.id,
            "username": user.username,
            "display_name": user.get_display_name(),
            "source": user.source,
            "is_superuser": user.is_superuser,
        }
        return data


class UserBriefSerializer(serializers.ModelSerializer):
    """当前用户信息:含角色编码与权限 codename 列表,供前端做菜单/按钮级控制。"""

    roles = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "display_name",
            "source",
            "phone",
            "email",
            "is_active",
            "is_superuser",
            "roles",
            "permissions",
            "last_login",
            "date_joined",
        ]
        read_only_fields = fields

    def get_roles(self, obj):
        return list(obj.roles.filter(enabled=True).values_list("code", flat=True))

    def get_permissions(self, obj):
        return sorted(obj.all_permission_codenames())
