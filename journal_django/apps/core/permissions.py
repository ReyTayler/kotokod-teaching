"""
Permission classes for journal_django.
"""
from __future__ import annotations

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


def _authenticated_with_role(request: Request, *roles: str) -> bool:
    """Return True if the request user is authenticated and has one of the given roles."""
    user = request.user
    # UNAUTHENTICATED_USER=None → при отсутствии токена request.user is None.
    # Зеркалим штатный DRF IsAuthenticated: сперва truthy-проверка, потом is_authenticated.
    if not (user and user.is_authenticated):
        return False
    return user.role in roles


class IsTeacher(BasePermission):
    """Allow access only to accounts with role 'teacher'."""
    message = 'Teacher role required.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        return _authenticated_with_role(request, 'teacher')


class IsManager(BasePermission):
    """Allow access only to accounts with role 'manager'."""
    message = 'Manager role required.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        return _authenticated_with_role(request, 'manager')


class IsAdmin(BasePermission):
    """Allow access only to accounts with role 'admin'."""
    message = 'Admin role required.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        return _authenticated_with_role(request, 'admin')


class IsManagerOrAdmin(BasePermission):
    """Allow access to accounts with role 'manager' or 'admin'."""
    message = 'Manager or admin role required.'

    def has_permission(self, request: Request, view: APIView) -> bool:
        return _authenticated_with_role(request, 'manager', 'admin')