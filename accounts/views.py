from collections import OrderedDict

from django import forms
from django.contrib import messages
from django.contrib.auth.hashers import make_password
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from accounts.forms import (
    CompanyRoleForm,
    PermissionDefinitionForm,
    UserAccountCreateForm,
    UserAccountUpdateForm,
)
from accounts.mixins import RolePermissionMixin, company_admin_required
from accounts.models import Permission, Role, RolePermission, UserAccount, UserDepartment, UserPermission, UserRole


PERMISSION_CATALOG = {
    "Users": ("View", "Create", "Edit", "Delete", "Update"),
    "Roles": ("View", "Create", "Edit", "Delete", "Update"),
    "Permissions": ("View", "Create", "Edit", "Delete", "Update"),
    "Departments": ("View", "Create", "Edit", "Delete", "Update"),
    "Organization Units": ("View", "Create", "Edit", "Delete", "Update"),
    "Facilities": ("View", "Create", "Edit", "Delete", "Update"),
    "Company Profile": ("View", "Create", "Edit", "Delete", "Update"),
    "ESG Data": ("View", "Create", "Edit", "Delete", "Update"),
    "Reports": ("View",),
}
MATRIX_ACTIONS = ("View", "Create", "Edit", "Delete", "Update")


def _ensure_permission_catalog():
    for module, actions in PERMISSION_CATALOG.items():
        slug = module.lower().replace(" ", "_")
        for action in actions:
            Permission.objects.get_or_create(
                code=f"{slug}.{action.lower()}",
                defaults={"name": f"{action} {module}", "module": module},
            )


def _sync_user_relations(user, department, permissions, assigned_by):
    UserDepartment.objects.filter(user=user).delete()
    if department:
        UserDepartment.objects.create(user=user, department=department)
    UserPermission.objects.filter(user=user).exclude(permission__in=permissions).delete()
    for permission in permissions:
        UserPermission.objects.get_or_create(user=user, permission=permission)
    UserRole.objects.filter(user=user).exclude(role=user.role).delete()
    UserRole.objects.get_or_create(user=user, role=user.role, defaults={"assigned_by": assigned_by})


class CompanyObjectMixin(RolePermissionMixin):
    """Shared company tenancy and role-permission protection for account CBVs."""

    def get_company_user(self, user_id):
        return get_object_or_404(
            UserAccount.objects.select_related("role", "company"),
            id=user_id,
            company=self.request.company,
        )

    def get_company_role(self, role_id):
        return get_object_or_404(Role, id=role_id, company=self.request.company)


class UserListView(CompanyObjectMixin, ListView):
    template_name = "accounts/user_list.html"
    context_object_name = "users"
    required_permission = "users.view"

    def get_queryset(self):
        queryset = UserAccount.objects.filter(company=self.request.company).select_related("role")
        query, active = self.request.GET.get("q", "").strip(), self.request.GET.get("active", "")
        if query:
            queryset = queryset.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(email__icontains=query) | Q(role__name__icontains=query))
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        return queryset.order_by("first_name", "email")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"query": self.request.GET.get("q", ""), "active_filter": self.request.GET.get("active", "")})
        return context


class UserCreateView(CompanyObjectMixin, FormView):
    template_name = "accounts/user_form.html"
    form_class = UserAccountCreateForm
    required_permission = "users.create"

    def dispatch(self, request, *args, **kwargs):
        _ensure_permission_catalog()
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.company
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create User"
        return context

    def form_valid(self, form):
        user = form.save(commit=False)
        user.company = self.request.company
        user.password = make_password(form.cleaned_data["password"])
        user.save()
        _sync_user_relations(user, form.cleaned_data["department"], form.cleaned_data["permissions"], self.request.user_account)
        messages.success(self.request, "User created successfully.")
        return redirect("account-user-detail", user_id=user.id)


class UserDetailView(CompanyObjectMixin, DetailView):
    template_name = "accounts/user_detail.html"
    context_object_name = "managed_user"
    required_permission = "users.view"

    def get_object(self, queryset=None):
        return self.get_company_user(self.kwargs["user_id"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.object
        context["department"] = user.user_departments.select_related("department").first()
        context["permissions"] = user.user_permissions.select_related("permission").order_by("permission__module", "permission__name")
        return context


class UserUpdateView(CompanyObjectMixin, FormView):
    template_name = "accounts/user_form.html"
    form_class = UserAccountUpdateForm
    required_permission = ("users.edit", "users.update")

    def dispatch(self, request, *args, **kwargs):
        _ensure_permission_catalog()
        return super().dispatch(request, *args, **kwargs)

    def get_managed_user(self):
        if not hasattr(self, "managed_user"):
            self.managed_user = self.get_company_user(self.kwargs["user_id"])
        return self.managed_user

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update({"company": self.request.company, "instance": self.get_managed_user()})
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Edit User"
        return context

    def form_valid(self, form):
        user = form.save()
        _sync_user_relations(user, form.cleaned_data["department"], form.cleaned_data["permissions"], self.request.user_account)
        messages.success(self.request, "User updated successfully.")
        return redirect("account-user-detail", user_id=user.id)


class UserStatusView(CompanyObjectMixin, View):
    active = True
    required_permission = ("users.edit", "users.update")

    def post(self, request, user_id):
        user = self.get_company_user(user_id)
        if not self.active and user == request.user_account:
            messages.error(request, "You cannot deactivate your own account.")
        else:
            user.is_active = self.active
            user.save(update_fields=["is_active", "updated_at"])
            messages.success(request, "User activated." if self.active else "User deactivated.")
        return redirect("account-user-detail", user_id=user.id)


class UserActivateView(UserStatusView):
    active = True


class UserDeactivateView(UserStatusView):
    active = False


class RoleListView(CompanyObjectMixin, ListView):
    template_name = "accounts/role_list.html"
    context_object_name = "roles"
    required_permission = "roles.view"

    def get_queryset(self):
        queryset = Role.objects.filter(company=self.request.company).prefetch_related("role_permissions__permission")
        query, active = self.request.GET.get("q", "").strip(), self.request.GET.get("active", "")
        if query:
            queryset = queryset.filter(Q(name__icontains=query) | Q(description__icontains=query))
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        return queryset.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"query": self.request.GET.get("q", ""), "active_filter": self.request.GET.get("active", "")})
        return context


class RoleCreateView(CompanyObjectMixin, FormView):
    template_name = "accounts/role_form.html"
    form_class = CompanyRoleForm
    required_permission = "roles.create"

    def dispatch(self, request, *args, **kwargs):
        _ensure_permission_catalog()
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.company
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create Role"
        return context

    def form_valid(self, form):
        role = form.save(commit=False)
        role.company = self.request.company
        role.save()
        form.instance = role
        form.save_permissions()
        messages.success(self.request, "Role created successfully.")
        return redirect("account-role-list")
    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        queryset = Role.objects.filter(
            company=self.company,
            name__iexact=name,
        )

        # Ignore the current role while editing
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise forms.ValidationError(
                "A role with this name already exists."
            )
        return name


class RoleUpdateView(CompanyObjectMixin, FormView):
    template_name = "accounts/role_form.html"
    form_class = CompanyRoleForm
    required_permission = ("roles.edit", "roles.update")

    def dispatch(self, request, *args, **kwargs):
        _ensure_permission_catalog()
        return super().dispatch(request, *args, **kwargs)

    def get_role(self):
        if not hasattr(self, "role"):
            self.role = self.get_company_role(self.kwargs["role_id"])
        return self.role

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update({"company": self.request.company, "instance": self.get_role()})
        return kwargs

    def _system_role_redirect(self):
        if self.get_role().is_system_role:
            messages.error(self.request, "System roles cannot be changed.")
            return redirect("account-role-list")
        return None

    def get(self, request, *args, **kwargs):
        return self._system_role_redirect() or super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return self._system_role_redirect() or super().post(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Edit Role"
        return context

    def form_valid(self, form):
        form.save()
        form.save_permissions()
        messages.success(self.request, "Role updated successfully.")
        return redirect("account-role-list")


class PermissionCreateView(CompanyObjectMixin, FormView):
    template_name = "accounts/permission_form.html"
    form_class = PermissionDefinitionForm
    company_admin_only = True

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Permissions created successfully.")
        return redirect("account-role-list")


class RolePermissionMatrixView(CompanyObjectMixin, TemplateView):
    template_name = "accounts/role_permission_matrix.html"
    required_permission = ("roles.edit", "roles.update")

    def dispatch(self, request, *args, **kwargs):
        _ensure_permission_catalog()
        return super().dispatch(request, *args, **kwargs)

    def get_role(self):
        if not hasattr(self, "role"):
            self.role = self.get_company_role(self.kwargs["role_id"])
        return self.role

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        by_module = OrderedDict()
        for permission in Permission.objects.order_by("module", "name"):
            module = permission.module or permission.name
            action = permission.code.rsplit(".", 1)[-1].lower()
            by_module.setdefault(module, {})[action] = permission
        context.update({
            "role": self.get_role(),
            "actions": MATRIX_ACTIONS,
            "permission_rows": [
                {"name": module, "cells": [entries.get(action.lower()) for action in MATRIX_ACTIONS]}
                for module, entries in by_module.items()
            ],
            "selected_permission_ids": set(self.get_role().role_permissions.values_list("permission_id", flat=True)),
        })
        return context

    def post(self, request, *args, **kwargs):
        selected_ids = request.POST.getlist("permissions")
        valid_ids = Permission.objects.filter(id__in=selected_ids).values_list("id", flat=True)
        role = self.get_role()
        RolePermission.objects.filter(role=role).exclude(permission_id__in=valid_ids).delete()
        for permission_id in valid_ids:
            RolePermission.objects.get_or_create(role=role, permission_id=permission_id)
        messages.success(request, f"Permissions updated for {role.name}.")
        return redirect("account-role-list")
