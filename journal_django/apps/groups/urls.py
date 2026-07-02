"""
URL маршруты для раздела groups.

Монтируются в config/urls.py как:
  path('api/admin/groups', include('apps.groups.urls'))

APPEND_SLASH=False — пути без trailing slash (зеркало Express/Nest).
"""
from django.urls import path

from apps.groups.views import (
    GroupDetailView, GroupListCreateView,
    GroupExceptionDeleteView, GroupExceptionsView,
    GroupScheduleChangeView, GroupScheduleView,
)

urlpatterns = [
    path('', GroupListCreateView.as_view(), name='groups-list-create'),
    path('/<int:pk>', GroupDetailView.as_view(), name='groups-detail'),
    # Расписание (Ф3): версионные слоты + разовые исключения
    path('/<int:pk>/schedule', GroupScheduleView.as_view(), name='groups-schedule'),
    path('/<int:pk>/schedule-change', GroupScheduleChangeView.as_view(), name='groups-schedule-change'),
    path('/<int:pk>/exceptions', GroupExceptionsView.as_view(), name='groups-exceptions'),
    path('/<int:pk>/exceptions/<int:eid>', GroupExceptionDeleteView.as_view(), name='groups-exception-delete'),
]
