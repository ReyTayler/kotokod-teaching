"""
URL маршруты для раздела students.

Монтируются в config/urls.py как:
  path('api/admin/students', include('apps.students.urls'))

APPEND_SLASH=False — пути без trailing slash (зеркало Express/Nest).
"""
from django.urls import path

from apps.students.views import (
    StudentBalanceView,
    StudentDetailView,
    StudentListCreateView,
    StudentStatsView,
)

urlpatterns = [
    path('', StudentListCreateView.as_view(), name='students-list-create'),
    path('/<int:pk>', StudentDetailView.as_view(), name='students-detail'),
    path('/<int:pk>/stats', StudentStatsView.as_view(), name='students-stats'),
    path('/<int:pk>/balance', StudentBalanceView.as_view(), name='students-balance'),
]
