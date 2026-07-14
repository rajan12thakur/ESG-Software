from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import FormView, ListView, TemplateView

from accounts.mixins import RolePermissionMixin
from accounts.rbac import (
    ResourceContext,
    SCOPE_TYPE_FACILITY,
    SCOPE_TYPE_ORG_UNIT,
    authorize,
    filter_authorized_queryset,
    has_permission_assignment,
)
from core.forms import CompanyProfileForm, DepartmentForm, FacilityForm, OrganizationUnitForm
from core.models import CompanyProfile, Department, Facility, OrganizationUnit


def org_unit_resource_context(unit: OrganizationUnit) -> ResourceContext:
    return ResourceContext.from_mapping({SCOPE_TYPE_ORG_UNIT: [unit.id]})


def facility_resource_context(facility: Facility) -> ResourceContext:
    return ResourceContext.from_mapping(
        {
            SCOPE_TYPE_FACILITY: [facility.id],
            SCOPE_TYPE_ORG_UNIT: [facility.organization_unit_id],
        }
    )


def org_unit_create_context(unit: OrganizationUnit | None) -> ResourceContext | None:
    if unit is None:
        return None
    return org_unit_resource_context(unit)


class HomeView(TemplateView):
    template_name = "home.html"


class CompanyAdminMixin(RolePermissionMixin):
    company_admin_only = True


class CompanyFormView(CompanyAdminMixin, FormView):
    template_name = "core/form.html"


class CompanyProfileView(CompanyFormView):
    form_class = CompanyProfileForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        self.profile, _ = CompanyProfile.objects.get_or_create(company=self.request.company)
        kwargs["instance"] = self.profile
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"title": "Company Profile", "cancel_url": "company-dashboard"})
        return context

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Company profile updated.")
        return redirect("company-profile")


class TenantPermissionViewMixin(RolePermissionMixin):
    def get_company_queryset(self, queryset):
        return queryset.filter(company=self.request.company)


class TenantPermissionListView(TenantPermissionViewMixin, ListView):
    template_name = "core/list.html"
    context_object_name = "items"
    model = None
    label = ""
    template_prefix = ""
    scope_filtered = False

    def has_required_permission(self, request):
        if super().has_required_permission(request):
            return True
        if (
            self.scope_filtered
            and getattr(request, "user_account", None)
            and has_permission_assignment(request.user_account, self.required_permission)
        ):
            return True
        return False

    def get_queryset(self):
        queryset = self.get_company_queryset(self.model.objects.all()).order_by("name")
        if not self.scope_filtered:
            return queryset
        return filter_authorized_queryset(
            queryset,
            user=self.request.user_account,
            permission_codes=self.required_permission,
            resource_context_builder=self.get_resource_context_for_object,
            is_company_admin=self.request.is_company_admin,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "label": self.label,
                "create_url": f"{self.template_prefix}-create",
                "edit_url": f"{self.template_prefix}-update",
            }
        )
        return context

    def get_resource_context_for_object(self, obj):
        return None


class TenantPermissionFormView(TenantPermissionViewMixin, FormView):
    template_name = "core/form.html"
    model = None
    label = ""
    template_prefix = ""
    form_requires_company = False

    def get_object(self):
        if not hasattr(self, "_object"):
            self._object = (
                get_object_or_404(
                    self.get_company_queryset(self.model.objects.all()),
                    id=self.kwargs["object_id"],
                )
                if "object_id" in self.kwargs
                else None
            )
        return self._object

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.form_requires_company:
            kwargs["company"] = self.request.company
        instance = self.get_object()
        if instance is not None:
            kwargs["instance"] = instance
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        editing = self.get_object() is not None
        context.update(
            {
                "title": f"{'Edit' if editing else 'Create'} {self.label}",
                "cancel_url": f"{self.template_prefix}-list",
            }
        )
        return context

    def get_resource_context(self, request):
        obj = self.get_object()
        return self.get_resource_context_for_object(obj) if obj is not None else None

    def get_resource_context_for_object(self, obj):
        return None

    def form_valid(self, form):
        item = form.save(commit=False)
        item.company = self.request.company
        item.save()
        messages.success(
            self.request,
            f"{self.label} {'updated' if self.get_object() else 'created'} successfully.",
        )
        return redirect(f"{self.template_prefix}-list")


class DepartmentListView(TenantPermissionListView):
    model = Department
    label = "Department"
    template_prefix = "company-department"
    required_permission = "departments.view"


class DepartmentCreateView(TenantPermissionFormView):
    model = Department
    form_class = DepartmentForm
    label = "Department"
    template_prefix = "company-department"
    required_permission = "departments.create"


class DepartmentUpdateView(DepartmentCreateView):
    required_permission = ("departments.edit", "departments.update")


class OrganizationUnitAccessMixin(TenantPermissionViewMixin):
    scope_filtered = True

    def get_resource_context_for_object(self, obj):
        return org_unit_resource_context(obj)

    def get_parent_queryset(self):
        queryset = self.get_company_queryset(OrganizationUnit.objects.all()).order_by("name")
        current_object = self.get_object()
        if current_object is not None:
            queryset = queryset.exclude(pk=current_object.pk)
        if self.request.is_company_admin or authorize(
            self.request.user_account,
            self.required_permission,
            is_company_admin=self.request.is_company_admin,
        ):
            return queryset
        return filter_authorized_queryset(
            queryset,
            user=self.request.user_account,
            permission_codes=self.required_permission,
            resource_context_builder=org_unit_resource_context,
            is_company_admin=self.request.is_company_admin,
        )

    def get_requested_parent(self):
        parent_id = self.request.POST.get("parent_unit")
        if not parent_id:
            return None
        return get_object_or_404(
            self.get_company_queryset(OrganizationUnit.objects.all()),
            id=parent_id,
        )

    def parent_is_authorized(self, parent_unit):
        return authorize(
            self.request.user_account,
            self.required_permission,
            org_unit_create_context(parent_unit),
            is_company_admin=self.request.is_company_admin,
        )


class OrganizationUnitListView(OrganizationUnitAccessMixin, TenantPermissionListView):
    model = OrganizationUnit
    label = "Organization Unit"
    template_prefix = "company-unit"
    required_permission = "organization_units.view"


class OrganizationUnitCreateView(OrganizationUnitAccessMixin, TenantPermissionFormView):
    model = OrganizationUnit
    form_class = OrganizationUnitForm
    label = "Organization Unit"
    template_prefix = "company-unit"
    form_requires_company = True
    required_permission = "organization_units.create"

    def has_required_permission(self, request):
        if super().has_required_permission(request):
            return True
        if not getattr(request, "user_account", None):
            return False
        if request.method == "POST":
            parent_unit = self.get_requested_parent()
            return self.parent_is_authorized(parent_unit)
        return self.get_parent_queryset().exists()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["parent_queryset"] = self.get_parent_queryset()
        return kwargs

    def form_valid(self, form):
        parent_unit = form.cleaned_data.get("parent_unit")
        if not authorize(
            self.request.user_account,
            self.required_permission,
            org_unit_create_context(parent_unit),
            is_company_admin=self.request.is_company_admin,
        ):
            raise PermissionDenied("You do not have permission to create this organization unit.")
        return super().form_valid(form)


class OrganizationUnitUpdateView(OrganizationUnitCreateView):
    required_permission = ("organization_units.edit", "organization_units.update")

    def has_required_permission(self, request):
        return super(OrganizationUnitCreateView, self).has_required_permission(request)

    def form_valid(self, form):
        parent_unit = form.cleaned_data.get("parent_unit")
        if parent_unit is not None and not self.parent_is_authorized(parent_unit):
            raise PermissionDenied("You do not have permission to reassign this organization unit.")
        return super(OrganizationUnitCreateView, self).form_valid(form)


class FacilityAccessMixin(TenantPermissionViewMixin):
    scope_filtered = True

    def get_unit(self):
        if not hasattr(self, "_unit"):
            self._unit = get_object_or_404(
                self.get_company_queryset(OrganizationUnit.objects.all()),
                id=self.kwargs["unit_id"],
            )
        return self._unit

    def get_resource_context_for_object(self, obj):
        return facility_resource_context(obj)

    def get_create_resource_context(self):
        return ResourceContext.from_mapping(
            {SCOPE_TYPE_ORG_UNIT: [self.get_unit().id]}
        )


class UnitFacilityListView(FacilityAccessMixin, TenantPermissionListView):
    template_name = "core/facility_list.html"
    context_object_name = "facilities"
    model = Facility
    required_permission = "facilities.view"

    def has_required_permission(self, request):
        if super().has_required_permission(request):
            return True
        if getattr(request, "user_account", None):
            return has_permission_assignment(request.user_account, self.required_permission)
        return False

    def get_queryset(self):
        queryset = self.get_company_queryset(Facility.objects.filter(organization_unit=self.get_unit())).order_by("name")
        return filter_authorized_queryset(
            queryset,
            user=self.request.user_account,
            permission_codes=self.required_permission,
            resource_context_builder=self.get_resource_context_for_object,
            is_company_admin=self.request.is_company_admin,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["unit"] = self.get_unit()
        return context


class UnitFacilityFormView(FacilityAccessMixin, TenantPermissionFormView):
    form_class = FacilityForm

    def get_resource_context(self, request):
        obj = self.get_object()
        if obj is not None:
            return self.get_resource_context_for_object(obj)
        return self.get_create_resource_context()

    def get_object(self):
        if not hasattr(self, "_object"):
            self._object = (
                get_object_or_404(
                    self.get_company_queryset(Facility.objects.filter(organization_unit=self.get_unit())),
                    id=self.kwargs["object_id"],
                )
                if "object_id" in self.kwargs
                else None
            )
        return self._object

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update({"company": self.request.company, "organization_unit": self.get_unit()})
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        unit, facility = self.get_unit(), self.get_object()
        context.update(
            {
                "title": f"{'Edit Facility: ' + facility.name if facility else 'Create Facility for ' + unit.name}",
                "cancel_url": "company-unit-facility-list",
                "cancel_args": [unit.id],
            }
        )
        return context

    def form_valid(self, form):
        if not authorize(
            self.request.user_account,
            self.required_permission,
            self.get_resource_context(self.request),
            is_company_admin=self.request.is_company_admin,
        ):
            raise PermissionDenied("You do not have permission to modify this facility.")
        facility = form.save(commit=False)
        facility.company = self.request.company
        facility.organization_unit = self.get_unit()
        facility.save()
        messages.success(
            self.request,
            "Facility updated successfully." if self.get_object() else "Facility created successfully.",
        )
        return redirect("company-unit-facility-list", unit_id=self.get_unit().id)


class UnitFacilityCreateView(UnitFacilityFormView):
    label = "Facility"
    template_prefix = "company-unit-facility"
    required_permission = "facilities.create"


class UnitFacilityUpdateView(UnitFacilityFormView):
    label = "Facility"
    template_prefix = "company-unit-facility"
    required_permission = ("facilities.edit", "facilities.update")
