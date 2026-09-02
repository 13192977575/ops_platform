from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import EndpointInvokeView, EndpointViewSet

router = DefaultRouter()
router.register("endpoints", EndpointViewSet, basename="endpoint")

urlpatterns = router.urls + [
    path(
        "endpoints/invoke/<str:code>/",
        EndpointInvokeView.as_view(),
        name="endpoint-invoke",
    ),
]
