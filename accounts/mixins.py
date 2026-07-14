from functools import wraps

from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from accounts.rbac import authorize


class RolePermissionMixin:
    """Check tenant permissions for company views."""

    required_permission = None
    company_admin_only = False

    def get_resource_context(self, request):
        """Override to provide scope context."""

        return None

    def has_required_permission(self, request):
        if request.is_company_admin:
            return True
        if self.company_admin_only:
            return False
        if not self.required_permission or not getattr(request, "user_account", None):
            return False

        return authorize(
            request.user_account,
            self.required_permission,
            self.get_resource_context(request),
            is_company_admin=request.is_company_admin,
        )

    def dispatch(self, request, *args, **kwargs):
        if not getattr(request, "user_account", None):
            return redirect("company-login")
        if not self.has_required_permission(request):
            return HttpResponseForbidden(
                "You do not have permission to access this page."
            )
        return super().dispatch(request, *args, **kwargs)


def company_admin_required(view_func):
    """Require a company admin."""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not getattr(request, "user_account", None):
            return redirect("company-login")
        if not request.is_company_admin:
            return HttpResponseForbidden("Company administrator access is required.")
        return view_func(request, *args, **kwargs)

    return wrapper
