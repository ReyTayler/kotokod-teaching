"""Маршруты renewals. APPEND_SLASH=False — без trailing slash."""
from django.urls import path

from apps.renewals.views import RenewalCollectionView, RenewalDetailView

urlpatterns = [
    path('', RenewalCollectionView.as_view(), name='renewals-collection'),
    path('/<int:pk>', RenewalDetailView.as_view(), name='renewals-detail'),
]
