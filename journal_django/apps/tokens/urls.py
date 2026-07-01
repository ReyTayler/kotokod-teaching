"""
URL маршруты для раздела tokens.

Монтируются в config/urls.py как:
  path('api/admin/tokens', include('apps.tokens.urls'))

ВАЖНО: /generate смонтирован ПЕРЕД /<str:token>, иначе DRF
поймает слово 'generate' как значение параметра token.

PK — token (строка), не числовой id.
"""
from django.urls import path

from apps.tokens.views import TokenDetailView, TokenGenerateView, TokenListCreateView

urlpatterns = [
    path('', TokenListCreateView.as_view(), name='tokens-list-create'),
    path('/generate', TokenGenerateView.as_view(), name='tokens-generate'),
    path('/<str:token>', TokenDetailView.as_view(), name='tokens-detail'),
]
