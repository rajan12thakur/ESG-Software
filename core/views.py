from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import FormView, ListView, TemplateView

from accounts.mixins import RolePermissionMixin
from core.forms import CompanyProfileForm, DepartmentForm, FacilityForm, OrganizationUnitForm
from core.models import CompanyProfile, Department, Facility, OrganizationUnit


class HomeView(TemplateView):
    template_name = "home.html"


class CompanyAdminMixin(RolePermissionMixin):
    """Base for company records; company admins always retain full access."""


class CompanyFormView(CompanyAdminMixin, FormView):
    template_name = "core/company_profile_form.html"


class CompanyListView(CompanyAdminMixin, ListView):
    template_name = "core/department_list.html"
    context_object_name = "items"
    model = None
    label = ""
    template_prefix = ""
    permission_module = ""

    def get_queryset(self):
        queryset = self.model.objects.filter(company=self.request.company)
        query = self.request.GET.get("q", "").strip()
        active = self.request.GET.get("active", "")
        if query:
            queryset = queryset.filter(Q(name__icontains=query) | Q(description__icontains=query))
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        return queryset.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "label": self.label,
            "create_url": f"{self.template_prefix}-create",
            "edit_url": f"{self.template_prefix}-update",
            "delete_url": f"{self.template_prefix}-delete",
            "query": self.request.GET.get("q", ""),
            "active_filter": self.request.GET.get("active", ""),
        })
        return context


class CompanyModelFormView(CompanyFormView):
    model = None
    label = ""
    template_prefix = ""
    form_requires_company = False

    def get_object(self):
        return get_object_or_404(self.model, id=self.kwargs["object_id"], company=self.request.company) if "object_id" in self.kwargs else None

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.form_requires_company:
            kwargs["company"] = self.request.company
        if self.get_object():
            kwargs["instance"] = self.get_object()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        editing = self.get_object() is not None
        context.update({"title": f"{'Edit' if editing else 'Create'} {self.label}", "cancel_url": f"{self.template_prefix}-list"})
        return context

    def form_valid(self, form):
        item = form.save(commit=False)
        if not item.pk:
            item.company = self.request.company
        item.save()
        messages.success(self.request, f"{self.label} {'updated' if item.pk and self.get_object() else 'created'} successfully.")
        return redirect(f"{self.template_prefix}-list")


class CompanyProfileView(CompanyFormView):
    form_class = CompanyProfileForm
    template_name = "core/company_profile_form.html"
    required_permission = ("company_profile.edit", "company_profile.update")

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
        form.save(); messages.success(self.request, "Company profile updated.")
        return redirect("company-profile")


class CompanyDeleteView(CompanyAdminMixin, View):
    model = None
    template_prefix = ""
    label = ""

    def post(self, request, object_id):
        item = get_object_or_404(self.model, id=object_id, company=request.company)
        item.delete()
        messages.success(request, f"{self.label} deleted successfully.")
        return redirect(f"{self.template_prefix}-list")


class DepartmentListView(CompanyListView):
    model, label, template_prefix, template_name, required_permission = Department, "Department", "company-department", "core/department_list.html", "departments.view"


class DepartmentCreateView(CompanyModelFormView):
    model, form_class, label, template_prefix, template_name, required_permission = Department, DepartmentForm, "Department", "company-department", "core/department_form.html", "departments.create"


class DepartmentUpdateView(DepartmentCreateView):
    required_permission = ("departments.edit", "departments.update")


class DepartmentDeleteView(CompanyDeleteView):
    model, label, template_prefix, required_permission = Department, "Department", "company-department", "departments.delete"


class OrganizationUnitListView(CompanyListView):
    model, label, template_prefix, template_name, required_permission = OrganizationUnit, "Organization Unit", "company-unit", "core/organization_unit_list.html", "organization_units.view"

    def get_queryset(self):
        queryset = OrganizationUnit.objects.filter(company=self.request.company)
        query, active = self.request.GET.get("q", "").strip(), self.request.GET.get("active", "")
        if query:
            queryset = queryset.filter(Q(name__icontains=query) | Q(unit_type__icontains=query) | Q(country__icontains=query) | Q(city__icontains=query))
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        return queryset.order_by("name")


class OrganizationUnitCreateView(CompanyModelFormView):
    model, form_class, label, template_prefix, form_requires_company, template_name, required_permission = OrganizationUnit, OrganizationUnitForm, "Organization Unit", "company-unit", True, "core/organization_unit_form.html", "organization_units.create"


class OrganizationUnitUpdateView(OrganizationUnitCreateView):
    required_permission = ("organization_units.edit", "organization_units.update")


class OrganizationUnitDeleteView(CompanyDeleteView):
    model, label, template_prefix, required_permission = OrganizationUnit, "Organization Unit", "company-unit", "organization_units.delete"


class UnitFacilityListView(CompanyAdminMixin, ListView):
    template_name = "core/facility_list.html"
    context_object_name = "facilities"
    required_permission = "facilities.view"

    def get_unit(self):
        return get_object_or_404(OrganizationUnit, id=self.kwargs["unit_id"], company=self.request.company)

    def get_queryset(self):
        queryset = Facility.objects.filter(company=self.request.company, organization_unit=self.get_unit())
        query, active = self.request.GET.get("q", "").strip(), self.request.GET.get("active", "")
        if query:
            queryset = queryset.filter(Q(name__icontains=query) | Q(facility_type__icontains=query) | Q(country__icontains=query) | Q(city__icontains=query))
        if active in {"true", "false"}:
            queryset = queryset.filter(is_active=active == "true")
        return queryset.order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"unit": self.get_unit(), "query": self.request.GET.get("q", ""), "active_filter": self.request.GET.get("active", "")})
        return context


class UnitFacilityFormView(CompanyFormView):
    form_class = FacilityForm
    template_name = "core/facility_form.html"

    def get_unit(self):
        return get_object_or_404(OrganizationUnit, id=self.kwargs["unit_id"], company=self.request.company)

    def get_object(self):
        if "object_id" not in self.kwargs:
            return None
        return get_object_or_404(Facility, id=self.kwargs["object_id"], company=self.request.company, organization_unit=self.get_unit())

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs.update({"company": self.request.company, "organization_unit": self.get_unit()})
        if self.get_object():
            kwargs["instance"] = self.get_object()
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        unit, facility = self.get_unit(), self.get_object()
        context.update({"title": f"{'Edit Facility: ' + facility.name if facility else 'Create Facility for ' + unit.name}", "cancel_url": "company-unit-facility-list", "cancel_args": [unit.id]})
        return context

    def form_valid(self, form):
        unit, facility = self.get_unit(), form.save(commit=False)
        facility.company, facility.organization_unit = self.request.company, unit
        facility.save()
        messages.success(self.request, "Facility updated successfully." if self.get_object() else "Facility created successfully.")
        return redirect("company-unit-facility-list", unit_id=unit.id)


class UnitFacilityCreateView(UnitFacilityFormView):
    required_permission = "facilities.create"


class UnitFacilityUpdateView(UnitFacilityFormView):
    required_permission = ("facilities.edit", "facilities.update")


class UnitFacilityDeleteView(CompanyAdminMixin, View):
    required_permission = "facilities.delete"

    def post(self, request, unit_id, object_id):
        unit = get_object_or_404(OrganizationUnit, id=unit_id, company=request.company)
        facility = get_object_or_404(Facility, id=object_id, company=request.company, organization_unit=unit)
        facility.delete()
        messages.success(request, "Facility deleted successfully.")
        return redirect("company-unit-facility-list", unit_id=unit.id)
