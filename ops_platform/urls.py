"""项目路由。"""
from django.contrib import admin
from django.urls import include, path

from ops_platform.apps.common.views import dashboard as dashboard_view
from ops_platform.apps.common.views import health as health_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("dashboard/", dashboard_view, name="dashboard"),
    path("api/health/", health_view, name="health"),
    path("api/", include("ops_platform.apps.accounts.urls")),
    path("api/", include("ops_platform.apps.scripts.urls")),
    path("api/", include("ops_platform.apps.schedules.urls")),
    path("api/", include("ops_platform.apps.endpoints.urls")),
    path("api/", include("ops_platform.apps.executions.urls")),
    path("api/", include("ops_platform.apps.logs.urls")),
    path("api/", include("ops_platform.apps.audit.urls")),
    path("api/", include("ops_platform.apps.alerts.urls")),
]
