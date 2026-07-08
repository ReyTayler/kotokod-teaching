"""Маршруты renewals. APPEND_SLASH=False — без trailing slash."""
from django.urls import path

from apps.renewals.views import (
    RenewalActivityView,
    RenewalCollectionView,
    RenewalCommentView,
    RenewalDetailView,
    RenewalMoveView,
    RenewalStageDetailView,
    RenewalStageListView,
    RenewalStageReorderView,
)

urlpatterns = [
    path('', RenewalCollectionView.as_view(), name='renewals-collection'),
    # Литеральные /stages* — до /<int:pk>, чтобы не было двусмысленности путей.
    path('/stages', RenewalStageListView.as_view(), name='renewals-stages'),
    path('/stages/reorder', RenewalStageReorderView.as_view(), name='renewals-stages-reorder'),
    path('/stages/<int:pk>', RenewalStageDetailView.as_view(), name='renewals-stage-detail'),
    path('/<int:pk>', RenewalDetailView.as_view(), name='renewals-detail'),
    path('/<int:pk>/move', RenewalMoveView.as_view(), name='renewals-move'),
    path('/<int:pk>/comment', RenewalCommentView.as_view(), name='renewals-comment'),
    path('/<int:pk>/activity', RenewalActivityView.as_view(), name='renewals-activity'),
]
