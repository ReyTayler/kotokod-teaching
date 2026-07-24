"""
URL маршруты для раздела dashboard.

Монтируются в config/urls.py как:
  path('api/admin/dashboard', include('apps.dashboard.urls'))

APPEND_SLASH=False — пути без trailing slash (зеркало Express).
/monthly — литеральный путь, не конфликтует с корнем '' (точное совпадение).
"""
from django.urls import path

from apps.dashboard.fill_views import UnfilledLessonsView
from apps.dashboard.views import DashboardMonthlyView, DashboardView

urlpatterns = [
    path('', DashboardView.as_view(), name='dashboard'),
    path('/monthly', DashboardMonthlyView.as_view(), name='dashboard-monthly'),
    path('/unfilled-lessons', UnfilledLessonsView.as_view(), name='dashboard-unfilled-lessons'),
]
