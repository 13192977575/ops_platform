from rest_framework.routers import DefaultRouter

from .views import ScheduleTaskViewSet

router = DefaultRouter()
router.register("schedules", ScheduleTaskViewSet, basename="schedule")

urlpatterns = router.urls
