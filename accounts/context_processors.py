from accounts.models import RolePermission


def permission_flags(request):
    """Expose action flags for permission-aware navigation and templates."""
    modules = ("users", "roles", "departments", "organization_units", "facilities", "company_profile")
    actions = ("view", "create", "edit", "update", "delete")
    flags = {f"{module}_{action}": False for module in modules for action in actions}
    user = getattr(request, "user_account", None)
    if not user:
        return {"permission_flags": flags}
    if getattr(request, "is_company_admin", False):
        flags = {key: True for key in flags}
    elif getattr(request, "role", None):
        codes = set(RolePermission.objects.filter(role=request.role).values_list("permission__code", flat=True))
        for module in modules:
            for action in actions:
                flags[f"{module}_{action}"] = f"{module}.{action}" in codes
    return {"permission_flags": flags}
