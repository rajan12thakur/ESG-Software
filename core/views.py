from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods


def home_view(request):
    return render(request, "home.html")
from accounts.views import company_admin_required
from core.forms import CompanyProfileForm, DepartmentForm, FacilityForm, OrganizationUnitForm
from core.models import CompanyProfile, Department, Facility, OrganizationUnit


def _company_object_or_404(model, request, object_id):
    return get_object_or_404(model, id=object_id, company=request.company)


@company_admin_required
@require_http_methods(["GET", "POST"])
def profile_view(request: HttpRequest) -> HttpResponse:
    profile, _ = CompanyProfile.objects.get_or_create(company=request.company)
    form = CompanyProfileForm(request.POST or None, instance=profile)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Company profile updated.")
        return redirect("company-profile")
    return render(request, "core/form.html", {"form": form, "title": "Company Profile", "cancel_url": "company-dashboard"})


def _list_and_form_views(model, form_class, template_prefix, label):
    @company_admin_required
    @require_http_methods(["GET"])
    def list_view(request):
        return render(request, "core/list.html", {"items": model.objects.filter(company=request.company).order_by("name"), "label": label, "create_url": f"{template_prefix}-create", "edit_url": f"{template_prefix}-update"})

    @company_admin_required
    @require_http_methods(["GET", "POST"])
    def create_view(request):
        form = form_class(request.POST or None, company=request.company) if form_class in (OrganizationUnitForm, FacilityForm) else form_class(request.POST or None)
        if request.method == "POST" and form.is_valid():
            item = form.save(commit=False)
            item.company = request.company
            item.save()
            messages.success(request, f"{label} created successfully.")
            return redirect(f"{template_prefix}-list")
        return render(request, "core/form.html", {"form": form, "title": f"Create {label}", "cancel_url": f"{template_prefix}-list"})

    @company_admin_required
    @require_http_methods(["GET", "POST"])
    def update_view(request, object_id):
        item = _company_object_or_404(model, request, object_id)
        form = form_class(request.POST or None, instance=item, company=request.company) if form_class in (OrganizationUnitForm, FacilityForm) else form_class(request.POST or None, instance=item)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, f"{label} updated successfully.")
            return redirect(f"{template_prefix}-list")
        return render(request, "core/form.html", {"form": form, "title": f"Edit {label}", "cancel_url": f"{template_prefix}-list"})
    return list_view, create_view, update_view


department_list_view, department_create_view, department_update_view = _list_and_form_views(Department, DepartmentForm, "company-department", "Department")
unit_list_view, unit_create_view, unit_update_view = _list_and_form_views(OrganizationUnit, OrganizationUnitForm, "company-unit", "Organization Unit")
facility_list_view, facility_create_view, facility_update_view = _list_and_form_views(Facility, FacilityForm, "company-facility", "Facility")
