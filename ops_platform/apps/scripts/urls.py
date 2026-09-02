from rest_framework.routers import DefaultRouter

from .views import ScriptViewSet

router = DefaultRouter()
router.register("scripts", ScriptViewSet, basename="script")

urlpatterns = router.urls
