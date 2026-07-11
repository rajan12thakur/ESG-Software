from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.forms import CompanyRoleForm, UserAccountCreateForm, UserAccountUpdateForm
from accounts.models import Role, UserAccount, UserDepartment, UserRole


def company_admin_required(view_func):
    def wrapper(request: HttpRequest, *args, **kwargs):
        if not request.user_account:
            return redirect("company-login")
        if not request.is_company_admin:
            return render(request, "accounts/forbidden.html", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def _company_user_or_404(request: HttpRequest, user_id):
    return get_object_or_404(
        UserAccount.objects.select_related("role", "company"),
        id=user_id,
        company=request.company,
    )


def _sync_user_relations(user, departments, assigned_by):
    UserDepartment.objects.filter(user=user).exclude(department__in=departments).delete()
    for department in departments:
        UserDepartment.objects.get_or_create(user=user, department=department)
    UserRole.objects.filter(user=user).exclude(role=user.role).delete()
    UserRole.objects.get_or_create(user=user, role=user.role, defaults={"assigned_by": assigned_by})


@company_admin_required
@require_http_methods(["GET"])
def user_list_view(request: HttpRequest) -> HttpResponse:
    users = UserAccount.objects.filter(company=request.company).select_related("role").order_by("first_name", "email")
    return render(request, "accounts/user_list.html", {"users": users})


@company_admin_required
@require_http_methods(["GET", "POST"])
def user_create_view(request: HttpRequest) -> HttpResponse:
    form = UserAccountCreateForm(request.POST or None, company=request.company)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False)
        user.company = request.company
        user.password = make_password(form.cleaned_data["password"])
        user.save()
        _sync_user_relations(user, form.cleaned_data["departments"], request.user_account)
        messages.success(request, "User created successfully.")
        return redirect("account-user-detail", user_id=user.id)
    return render(request, "accounts/user_form.html", {"form": form, "title": "Create User"})


@company_admin_required
@require_http_methods(["GET"])
def user_detail_view(request: HttpRequest, user_id) -> HttpResponse:
    user = _company_user_or_404(request, user_id)
    return render(request, "accounts/user_detail.html", {"managed_user": user})


@company_admin_required
@require_http_methods(["GET", "POST"])
def user_update_view(request: HttpRequest, user_id) -> HttpResponse:
    user = _company_user_or_404(request, user_id)
    form = UserAccountUpdateForm(request.POST or None, instance=user, company=request.company)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        _sync_user_relations(user, form.cleaned_data["departments"], request.user_account)
        messages.success(request, "User updated successfully.")
        return redirect("account-user-detail", user_id=user.id)
    return render(request, "accounts/user_form.html", {"form": form, "title": "Edit User"})


@company_admin_required
@require_POST
def user_activate_view(request: HttpRequest, user_id) -> HttpResponse:
    user = _company_user_or_404(request, user_id)
    user.is_active = True
    user.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "User activated.")
    return redirect("account-user-detail", user_id=user.id)


@company_admin_required
@require_POST
def user_deactivate_view(request: HttpRequest, user_id) -> HttpResponse:
    user = _company_user_or_404(request, user_id)
    if user == request.user_account:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect("account-user-detail", user_id=user.id)
    user.is_active = False
    user.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "User deactivated.")
    return redirect("account-user-detail", user_id=user.id)


@company_admin_required
@require_http_methods(["GET"])
def role_list_view(request: HttpRequest) -> HttpResponse:
    roles = Role.objects.filter(company=request.company).prefetch_related("role_permissions__permission").order_by("name")
    return render(request, "accounts/role_list.html", {"roles": roles})


@company_admin_required
@require_http_methods(["GET", "POST"])
def role_create_view(request: HttpRequest) -> HttpResponse:
    form = CompanyRoleForm(request.POST or None, company=request.company)
    if request.method == "POST" and form.is_valid():
        role = form.save(commit=False)
        role.company = request.company
        role.save()
        form.instance = role
        form.save_permissions()
        messages.success(request, "Role created successfully.")
        return redirect("account-role-list")
    return render(request, "accounts/role_form.html", {"form": form, "title": "Create Role"})


@company_admin_required
@require_http_methods(["GET", "POST"])
def role_update_view(request: HttpRequest, role_id) -> HttpResponse:
    role = get_object_or_404(Role, id=role_id, company=request.company)
    if role.is_system_role:
        messages.error(request, "System roles cannot be changed.")
        return redirect("account-role-list")
    form = CompanyRoleForm(request.POST or None, instance=role, company=request.company)
    if request.method == "POST" and form.is_valid():
        form.save()
        form.save_permissions()
        messages.success(request, "Role updated successfully.")
        return redirect("account-role-list")
    return render(request, "accounts/role_form.html", {"form": form, "title": "Edit Role"})
