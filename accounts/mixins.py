from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from accounts.models import RolePermission


class RolePermissionMixin:
    """Protect company views with a permission assigned to the current role.

    Company administrators retain full access.  Set ``required_permission`` to
    a permission code (or an iterable of codes) on a class-based view.
    """

    required_permission = None
    company_admin_only = False

    def has_required_permission(self, request):
        if request.is_company_admin:
            return True
        if self.company_admin_only:
            return False
        if not self.required_permission or not request.role:
            return False

        codes = (self.required_permission if isinstance(self.required_permission, (list, tuple, set))
                 else (self.required_permission,))
        return RolePermission.objects.filter(
            role=request.role,
            permission__code__in=codes,
        ).exists()

    def dispatch(self, request, *args, **kwargs):
        if not getattr(request, "user_account", None):
            return redirect("company-login")
        if not self.has_required_permission(request):
            return HttpResponseForbidden(
                "You do not have permission to access this page."
            )
        return super().dispatch(request, *args, **kwargs)


def company_admin_required(view_func):
    """Compatibility decorator for legacy function-based company views."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not getattr(request, "user_account", None):
            return redirect("company-login")
        if not request.is_company_admin:
            return HttpResponseForbidden("Company administrator access is required.")
        return view_func(request, *args, **kwargs)

    return wrapper
