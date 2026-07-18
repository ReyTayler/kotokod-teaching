"""URL-маршруты admin-раздела extra_lessons. Монтируется как
/api/admin/extra-lessons в config/urls.py. APPEND_SLASH=False."""
from django.urls import path

from apps.extra_lessons.views import (
    ExtraLessonBurnView, ExtraLessonCancelView, ExtraLessonDetailView, ExtraLessonListCreateView,
)

urlpatterns = [
    path('', ExtraLessonListCreateView.as_view(), name='extra-lessons-list-create'),
    path('/<int:pk>', ExtraLessonDetailView.as_view(), name='extra-lessons-detail'),
    path('/<int:pk>/cancel', ExtraLessonCancelView.as_view(), name='extra-lessons-cancel'),
    path('/<int:pk>/burn', ExtraLessonBurnView.as_view(), name='extra-lessons-burn'),
]
