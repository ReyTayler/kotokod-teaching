"""
URL маршруты для раздела settings_app.

Монтируются в config/urls.py как:
  path('api/admin/settings', include('apps.settings_app.urls'))

Единственный путь: GET + PUT (не список, не :id).
"""
from django.urls import path

from apps.settings_app.views import AdminSettingsView

urlpatterns = [
    path('', AdminSettingsView.as_view(), name='admin-settings'),
]
