from collections import OrderedDict

from django.contrib import messages
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from accounts.forms import (
    CompanyRoleForm,
    UserAccountCreateForm,
    UserAccountUpdateForm,
)
from accounts.mixins import RolePermissionMixin
from accounts.models import Permission, Role, RolePermission, UserAccount, UserRole
from accounts.permission_catalog import (
    CANONICAL_PERMISSION_CODES,
    CANONICAL_PERMISSION_MATRIX,
    CATALOG_ACTION_ORDER,
)
from accounts.rbac import SCOPE_TYPE_FACILITY, SCOPE_TYPE_ORG_UNIT
from core.models import Facility, OrganizationUnit


USER_ROLE_PREFETCH = Prefetch(
    "user_roles",
    queryset=UserRole.objects.select_related("role").prefetch_related("scopes").order_by(
        "assigned_at",
        "role__name",
    ),
)


def _scope_type_label(scope_type):
    if scope_type == SCOPE_TYPE_ORG_UNIT:
        return "Organization Units"
    if scope_type == SCOPE_TYPE_FACILITY:
        return "Facilities"
    return scope_type.replace("_", " ").title()


def _build_scope_target_maps(company, users):
    org_unit_ids = set()
    facility_ids = set()

    for user in users:
        for assignment in user.user_roles.all():
            for scope in assignment.scopes.all():
                scope_type = scope.scope_type.upper()
                if scope_type == SCOPE_TYPE_ORG_UNIT:
                    org_unit_ids.add(scope.scope_id)
                elif scope_type == SCOPE_TYPE_FACILITY:
                    facility_ids.add(scope.scope_id)

    return {
        SCOPE_TYPE_ORG_UNIT: OrganizationUnit.objects.filter(
            company=company,
            id__in=org_unit_ids,
        ).in_bulk(),
        SCOPE_TYPE_FACILITY: Facility.objects.filter(
            company=company,
            id__in=facility_ids,
        ).in_bulk(),
    }


def _build_user_role_assignment_summaries(user, scope_target_maps):
    assignments = list(user.user_roles.all())
    summaries = []
    for assignment in assignments:
        grouped_targets = OrderedDict()
        for scope in assignment.scopes.all():
            scope_type = scope.scope_type.upper()
            scope_map = scope_target_maps.get(scope_type, {})
            target = scope_map.get(scope.scope_id)
            label = getattr(target, "name", str(scope.scope_id))
            grouped_targets.setdefault(scope_type, []).append(label)

        summaries.append(
            {
                "role": assignment.role,
                "is_unrestricted": not grouped_targets,
                "scope_groups": [
                    {
                        "scope_type": scope_type,
                        "label": _scope_type_label(scope_type),
                        "targets": sorted(targets),
                    }
                    for scope_type, targets in grouped_targets.items()
                ],
            }
        )
    return summaries


def _attach_role_assignment_summaries(users, company):
    users = list(users)
    scope_target_maps = _build_scope_target_maps(company, users)
    for user in users:
        user.role_assignment_summaries = _build_user_role_assignment_summaries(
            user,
            scope_target_maps,
        )
    return users


class CompanyObjectMixin(RolePermissionMixin):
    """Scope account views to the current company."""

    def get_company_user(self, user_id):
        return get_object_or_404(
            UserAccount.objects.select_related("company").prefetch_related(
                "user_departments__department",
                USER_ROLE_PREFETCH,
            ),
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
        return (
            UserAccount.objects.filter(company=self.request.company)
            .prefetch_related(USER_ROLE_PREFETCH)
            .order_by("first_name", "email")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["users"] = _attach_role_assignment_summaries(
            context["users"],
            self.request.company,
        )
        return context


class UserCreateView(CompanyObjectMixin, FormView):
    template_name = "accounts/user_form.html"
    form_class = UserAccountCreateForm
    required_permission = "users.create"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["company"] = self.request.company
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = "Create User"
        return context

    def form_valid(self, form):
        user = form.save_with_assignments(assigned_by=self.request.user_account)
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
        context["role_assignments"] = _build_user_role_assignment_summaries(
            user,
            _build_scope_target_maps(self.request.company, [user]),
        )
        return context


class UserUpdateView(CompanyObjectMixin, FormView):
    template_name = "accounts/user_form.html"
    form_class = UserAccountUpdateForm
    required_permission = ("users.edit", "users.update")

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
        user = form.save_with_assignments(assigned_by=self.request.user_account)
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
        return Role.objects.filter(company=self.request.company).prefetch_related("role_permissions__permission").order_by("name")


class RoleCreateView(CompanyObjectMixin, FormView):
    template_name = "accounts/role_form.html"
    form_class = CompanyRoleForm
    required_permission = "roles.create"

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


class RoleUpdateView(CompanyObjectMixin, FormView):
    template_name = "accounts/role_form.html"
    form_class = CompanyRoleForm
    required_permission = ("roles.edit", "roles.update")

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


class RolePermissionMatrixView(CompanyObjectMixin, TemplateView):
    template_name = "accounts/role_permission_matrix.html"
    required_permission = ("roles.edit", "roles.update")

    def get_role(self):
        if not hasattr(self, "role"):
            self.role = self.get_company_role(self.kwargs["role_id"])
        return self.role

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        permissions_by_code = Permission.objects.filter(
            code__in=CANONICAL_PERMISSION_CODES,
        ).in_bulk(field_name="code")
        context.update({
            "role": self.get_role(),
            "actions": CATALOG_ACTION_ORDER,
            "permission_rows": [
                {
                    "name": module,
                    "cells": [permissions_by_code.get(code) for code in actions.values()],
                }
                for module, actions in CANONICAL_PERMISSION_MATRIX.items()
            ],
            "selected_permission_ids": set(self.get_role().role_permissions.values_list("permission_id", flat=True)),
        })
        return context

    def post(self, request, *args, **kwargs):
        selected_ids = request.POST.getlist("permissions")
        valid_ids = tuple(
            Permission.objects.filter(
                id__in=selected_ids,
                code__in=CANONICAL_PERMISSION_CODES,
            ).values_list("id", flat=True)
        )
        role = self.get_role()
        RolePermission.objects.filter(
            role=role,
            permission__code__in=CANONICAL_PERMISSION_CODES,
        ).exclude(permission_id__in=valid_ids).delete()
        for permission_id in valid_ids:
            RolePermission.objects.get_or_create(role=role, permission_id=permission_id)
        messages.success(request, f"Permissions updated for {role.name}.")
        return redirect("account-role-list")
