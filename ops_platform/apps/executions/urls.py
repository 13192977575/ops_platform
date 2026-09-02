from rest_framework.routers import DefaultRouter

from .views import ExecutionViewSet

router = DefaultRouter()
router.register("executions", ExecutionViewSet, basename="execution")

urlpatterns = router.urls
