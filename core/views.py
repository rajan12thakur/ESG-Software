from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import FormView, ListView, TemplateView

from accounts.mixins import RolePermissionMixin
from core.forms import CompanyProfileForm, DepartmentForm, FacilityForm, OrganizationUnitForm
from core.models import CompanyProfile, Department, Facility, OrganizationUnit


class HomeView(TemplateView):
    template_name = "home.html"


class CompanyAdminMixin(RolePermissionMixin):
    company_admin_only = True


class CompanyFormView(CompanyAdminMixin, FormView):
    template_name = "core/form.html"


class CompanyListView(CompanyAdminMixin, ListView):
    template_name = "core/list.html"
    context_object_name = "items"
    model = None
    label = ""
    template_prefix = ""

    def get_queryset(self):
        return self.model.objects.filter(company=self.request.company).order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"label": self.label, "create_url": f"{self.template_prefix}-create", "edit_url": f"{self.template_prefix}-update"})
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


class DepartmentListView(CompanyListView): model, label, template_prefix = Department, "Department", "company-department"
class DepartmentCreateView(CompanyModelFormView): model, form_class, label, template_prefix = Department, DepartmentForm, "Department", "company-department"
class DepartmentUpdateView(DepartmentCreateView): pass
class OrganizationUnitListView(CompanyListView): model, label, template_prefix = OrganizationUnit, "Organization Unit", "company-unit"
class OrganizationUnitCreateView(CompanyModelFormView): model, form_class, label, template_prefix, form_requires_company = OrganizationUnit, OrganizationUnitForm, "Organization Unit", "company-unit", True
class OrganizationUnitUpdateView(OrganizationUnitCreateView): pass


class UnitFacilityListView(CompanyAdminMixin, ListView):
    template_name = "core/facility_list.html"
    context_object_name = "facilities"

    def get_unit(self):
        return get_object_or_404(OrganizationUnit, id=self.kwargs["unit_id"], company=self.request.company)

    def get_queryset(self):
        return Facility.objects.filter(company=self.request.company, organization_unit=self.get_unit()).order_by("name")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["unit"] = self.get_unit()
        return context


class UnitFacilityFormView(CompanyFormView):
    form_class = FacilityForm

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
    pass


class UnitFacilityUpdateView(UnitFacilityFormView):
    pass
