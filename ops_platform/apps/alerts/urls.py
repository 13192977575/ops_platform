from rest_framework.routers import DefaultRouter

from .views import AlertChannelViewSet, AlertRecordViewSet, AlertRuleViewSet

router = DefaultRouter()
router.register("alert-channels", AlertChannelViewSet, basename="alert-channel")
router.register("alert-rules", AlertRuleViewSet, basename="alert-rule")
router.register("alert-records", AlertRecordViewSet, basename="alert-record")

urlpatterns = router.urls
