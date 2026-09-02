from rest_framework.routers import DefaultRouter

from .views import LogEntryViewSet

router = DefaultRouter()
router.register("logs", LogEntryViewSet, basename="log")

urlpatterns = router.urls
