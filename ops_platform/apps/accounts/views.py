"""accounts 视图:登录、令牌刷新、当前用户信息。"""
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from ops_platform.apps.audit.services import (
    ACTION_LOGIN,
    ACTION_LOGIN_FAILED,
    request_ip,
    write_audit,
)

from .serializers import LoginSerializer, UserBriefSerializer


class LoginView(TokenObtainPairView):
    """POST /api/auth/login/  {username, password} → {access, refresh, user}

    登录成功/失败均写入审计日志。
    """

    serializer_class = LoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        username = request.data.get("username", "")
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            write_audit(
                None,
                ACTION_LOGIN_FAILED,
                detail={"username": username},
                ip=request_ip(request),
            )
            raise
        user = serializer.user
        write_audit(
            user,
            ACTION_LOGIN,
            detail={"username": getattr(user, "username", "")},
            ip=request_ip(request),
        )
        return Response(serializer.validated_data, status=200)


class MeView(generics.RetrieveAPIView):
    """GET /api/auth/me/  返回当前登录用户信息(含角色与权限)。"""

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserBriefSerializer

    def get_object(self):
        return self.request.user


__all__ = ["LoginView", "TokenRefreshView", "MeView"]
