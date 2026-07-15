from dataclasses import dataclass

from django import forms
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from accounts.models import (
    Permission,
    Role,
    UserAccount,
    UserDepartment,
    UserRole,
    UserRoleScope,
)
from accounts.permission_catalog import CANONICAL_PERMISSION_CODES
from accounts.rbac import SCOPE_TYPE_FACILITY, SCOPE_TYPE_ORG_UNIT
from core.models import Department, Facility, OrganizationUnit


@dataclass(frozen=True)
class RoleScopeFieldGroup:
    role: Role
    org_unit_field_name: str
    facility_field_name: str


class CompanyRoleForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Role
        fields = ["name", "description", "is_active"]

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["permissions"].queryset = Permission.objects.filter(
            code__in=CANONICAL_PERMISSION_CODES,
        ).order_by("module", "name")
        if self.instance.pk:
            self.fields["permissions"].initial = self.instance.role_permissions.values_list("permission_id", flat=True)

    def save_permissions(self):
        from accounts.models import RolePermission
        RolePermission.objects.filter(role=self.instance).exclude(
            permission__in=self.cleaned_data["permissions"]
        ).delete()
        for permission in self.cleaned_data["permissions"]:
            RolePermission.objects.get_or_create(role=self.instance, permission=permission)


class BaseUserAccountForm(forms.ModelForm):
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        help_text="Select one or more roles. Leave the scope selectors empty for an unrestricted assignment.",
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.none(),
        required=False,
        empty_label="Select a department",
    )

    class Meta:
        model = UserAccount
        fields = [
            "employee_code",
            "first_name",
            "last_name",
            "email",
            "phone",
            "is_active",
        ]

    def __init__(self, *args, company, **kwargs):
        self.company = company
        super().__init__(*args, **kwargs)
        self.role_queryset = Role.objects.filter(company=company).order_by("name")
        self.org_unit_queryset = OrganizationUnit.objects.filter(company=company).order_by("name")
        self.facility_queryset = Facility.objects.filter(company=company).order_by("name")
        self.fields["roles"].queryset = self.role_queryset
        self.fields["department"].queryset = Department.objects.filter(
            company=company,
            is_active=True,
        ).order_by("name")
        self._role_scope_field_groups = []
        self._configure_scope_fields()
        self._set_initial_relations()

    def _configure_scope_fields(self):
        for role in self.role_queryset:
            org_unit_field_name = self.scope_field_name(role, SCOPE_TYPE_ORG_UNIT)
            facility_field_name = self.scope_field_name(role, SCOPE_TYPE_FACILITY)
            self.fields[org_unit_field_name] = forms.ModelMultipleChoiceField(
                queryset=self.org_unit_queryset,
                required=False,
                label=f"{role.name}: organization units",
                help_text="Leave blank to avoid restricting this assignment by organization unit.",
                widget=forms.CheckboxSelectMultiple,
            )
            self.fields[facility_field_name] = forms.ModelMultipleChoiceField(
                queryset=self.facility_queryset,
                required=False,
                label=f"{role.name}: facilities",
                help_text="Leave blank to avoid restricting this assignment by facility.",
                widget=forms.CheckboxSelectMultiple,
            )
            self._role_scope_field_groups.append(
                RoleScopeFieldGroup(
                    role=role,
                    org_unit_field_name=org_unit_field_name,
                    facility_field_name=facility_field_name,
                )
            )

    def _set_initial_relations(self):
        if not self.instance.pk:
            return

        assignment_map = {
            assignment.role_id: assignment
            for assignment in self.instance.user_roles.select_related("role").prefetch_related("scopes")
        }
        self.fields["roles"].initial = list(assignment_map.keys())
        self.fields["department"].initial = self.instance.user_departments.values_list(
            "department_id",
            flat=True,
        ).first()

        for group in self._role_scope_field_groups:
            assignment = assignment_map.get(group.role.id)
            if assignment is None:
                continue
            self.fields[group.org_unit_field_name].initial = [
                scope.scope_id
                for scope in assignment.scopes.all()
                if scope.scope_type.upper() == SCOPE_TYPE_ORG_UNIT
            ]
            self.fields[group.facility_field_name].initial = [
                scope.scope_id
                for scope in assignment.scopes.all()
                if scope.scope_type.upper() == SCOPE_TYPE_FACILITY
            ]

    @staticmethod
    def scope_field_name(role, scope_type):
        return f"role_scopes__{role.id}__{scope_type.lower()}"

    @property
    def primary_fields(self):
        field_names = [
            "employee_code",
            "first_name",
            "last_name",
            "email",
            "phone",
        ]
        if "password" in self.fields:
            field_names.append("password")
        field_names.extend(["department", "is_active"])
        return [self[field_name] for field_name in field_names]

    @property
    def scope_configuration_groups(self):
        selected_role_ids = set(self._selected_role_ids_for_display())
        groups = []
        for group in self._role_scope_field_groups:
            org_unit_selected_ids = self._selected_ids_for_scope_field(
                group.org_unit_field_name
            )
            facility_selected_ids = self._selected_ids_for_scope_field(
                group.facility_field_name
            )
            groups.append(
                {
                    "role": group.role,
                    "selected": str(group.role.id) in selected_role_ids,
                    "org_units_field": self[group.org_unit_field_name],
                    "facilities_field": self[group.facility_field_name],
                    "org_unit_rows": self._organization_unit_rows(org_unit_selected_ids),
                    "facility_sections": self._facility_sections(facility_selected_ids),
                }
            )
        return groups

    def _selected_role_ids_for_display(self):
        if self.is_bound:
            return [role_id for role_id in self.data.getlist("roles") if role_id]
        initial = self.fields["roles"].initial or []
        return [str(role_id) for role_id in initial]

    def _selected_ids_for_scope_field(self, field_name):
        if self.is_bound:
            return {
                str(value)
                for value in self.data.getlist(field_name)
                if value
            }

        initial = self.fields[field_name].initial or []
        return {str(value) for value in initial}

    def _organization_unit_rows(self, selected_ids):
        rows = []
        units_by_parent_id = {}
        for unit in self.org_unit_queryset:
            units_by_parent_id.setdefault(unit.parent_unit_id, []).append(unit)

        for siblings in units_by_parent_id.values():
            siblings.sort(key=lambda item: item.name.lower())

        def walk(parent_id, depth):
            for unit in units_by_parent_id.get(parent_id, []):
                rows.append(
                    {
                        "id": str(unit.id),
                        "name": unit.name,
                        "depth": depth,
                        "indent_steps": range(depth),
                        "meta": unit.unit_type,
                        "checked": str(unit.id) in selected_ids,
                    }
                )
                walk(unit.id, depth + 1)

        walk(None, 0)
        return rows

    def _facility_sections(self, selected_ids):
        ordered_units = self._organization_unit_rows(set())
        facilities_by_unit_id = {}
        for facility in self.facility_queryset:
            facilities_by_unit_id.setdefault(str(facility.organization_unit_id), []).append(facility)

        for facilities in facilities_by_unit_id.values():
            facilities.sort(key=lambda item: item.name.lower())

        sections = []
        for row in ordered_units:
            facilities = facilities_by_unit_id.get(row["id"], [])
            if not facilities:
                continue
            sections.append(
                {
                    "name": row["name"],
                    "depth": row["depth"],
                    "indent_steps": range(row["depth"]),
                    "facility_indent_steps": range(row["depth"] + 1),
                    "facilities": [
                        {
                            "id": str(facility.id),
                            "name": facility.name,
                            "meta": facility.facility_type,
                            "checked": str(facility.id) in selected_ids,
                        }
                        for facility in facilities
                    ],
                }
            )
        return sections

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        queryset = UserAccount.objects.filter(company=self.company, email__iexact=email)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("This email is already used in this company.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        selected_roles = cleaned_data.get("roles")
        if selected_roles is None:
            return cleaned_data

        raw_role_ids = [role_id for role_id in self.data.getlist("roles") if role_id]
        if not raw_role_ids:
            self.add_error("roles", "Select at least one role.")
            return cleaned_data
        if len(raw_role_ids) != len(set(raw_role_ids)):
            self.add_error("roles", "Duplicate role assignments are not allowed.")

        selected_roles_by_id = {str(role.id): role for role in selected_roles}
        ordered_roles = []
        for role_id in raw_role_ids:
            role = selected_roles_by_id.get(role_id)
            if role is not None and role not in ordered_roles:
                ordered_roles.append(role)
        if not ordered_roles and selected_roles:
            ordered_roles = list(selected_roles)

        role_payloads_by_role_id = {}
        for group in self._role_scope_field_groups:
            raw_org_unit_ids = [value for value in self.data.getlist(group.org_unit_field_name) if value]
            raw_facility_ids = [value for value in self.data.getlist(group.facility_field_name) if value]
            if len(raw_org_unit_ids) != len(set(raw_org_unit_ids)):
                self.add_error(
                    group.org_unit_field_name,
                    "Duplicate organization unit scope values are not allowed.",
                )
            if len(raw_facility_ids) != len(set(raw_facility_ids)):
                self.add_error(
                    group.facility_field_name,
                    "Duplicate facility scope values are not allowed.",
                )

            if group.role not in ordered_roles:
                if raw_org_unit_ids or raw_facility_ids:
                    error_message = "Select this role before assigning scopes."
                    self.add_error(group.org_unit_field_name, error_message)
                    self.add_error(group.facility_field_name, error_message)
                continue

            org_units = cleaned_data.get(group.org_unit_field_name)
            facilities = cleaned_data.get(group.facility_field_name)
            role_payloads_by_role_id[group.role.id] = {
                "role": group.role,
                "scope_rows": [
                    *[
                        (SCOPE_TYPE_ORG_UNIT, org_unit.id)
                        for org_unit in (org_units or [])
                    ],
                    *[
                        (SCOPE_TYPE_FACILITY, facility.id)
                        for facility in (facilities or [])
                    ],
                ],
            }

        cleaned_data["role_assignment_payloads"] = [
            role_payloads_by_role_id[role.id]
            for role in ordered_roles
            if role.id in role_payloads_by_role_id
        ]
        return cleaned_data

    def save_with_assignments(self, *, assigned_by):
        user = super().save(commit=False)
        role_assignment_payloads = self.cleaned_data["role_assignment_payloads"]
        user.company = self.company
        self._apply_additional_fields(user)

        with transaction.atomic():
            user.save()
            self._sync_department(user)
            self._sync_role_assignments(user, role_assignment_payloads, assigned_by)

        return user

    def _apply_additional_fields(self, user):
        return None

    def _sync_department(self, user):
        UserDepartment.objects.filter(user=user).delete()
        department = self.cleaned_data.get("department")
        if department:
            UserDepartment.objects.create(user=user, department=department)

    def _sync_role_assignments(self, user, role_assignment_payloads, assigned_by):
        selected_role_ids = [payload["role"].id for payload in role_assignment_payloads]
        UserRole.objects.filter(user=user).exclude(role_id__in=selected_role_ids).delete()
        existing_assignments = {
            assignment.role_id: assignment
            for assignment in UserRole.objects.filter(user=user).prefetch_related("scopes")
        }

        for payload in role_assignment_payloads:
            role = payload["role"]
            assignment = existing_assignments.get(role.id)
            if assignment is None:
                assignment = UserRole.objects.create(
                    user=user,
                    role=role,
                    assigned_by=assigned_by,
                )
            assignment.scopes.all().delete()
            UserRoleScope.objects.bulk_create(
                [
                    UserRoleScope(
                        user_role=assignment,
                        scope_type=scope_type,
                        scope_id=scope_id,
                    )
                    for scope_type, scope_id in payload["scope_rows"]
                ]
            )


class UserAccountCreateForm(BaseUserAccountForm):
    password = forms.CharField(widget=forms.PasswordInput)

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def _apply_additional_fields(self, user):
        user.password = make_password(self.cleaned_data["password"])


class UserAccountUpdateForm(BaseUserAccountForm):
    pass
