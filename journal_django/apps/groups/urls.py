"""
URL маршруты для раздела groups.

Монтируются в config/urls.py как:
  path('api/admin/groups', include('apps.groups.urls'))

APPEND_SLASH=False — пути без trailing slash (зеркало Express/Nest).
"""
from django.urls import path

from apps.groups.views import GroupDetailView, GroupListCreateView

urlpatterns = [
    path('', GroupListCreateView.as_view(), name='groups-list-create'),
    path('/<int:pk>', GroupDetailView.as_view(), name='groups-detail'),
]
