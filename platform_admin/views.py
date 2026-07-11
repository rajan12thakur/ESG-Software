from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.hashers import make_password
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import Role, UserAccount
from core.models import Company
from platform_admin.forms import CompanyForm, FirstCompanyAdminForm


def _is_platform_admin(user) -> bool:
    return user.is_authenticated and user.is_staff


def platform_admin_required(view_func):
    return login_required(
        user_passes_test(_is_platform_admin, login_url="platform-login")(view_func),
        login_url="platform-login",
    )


@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    if _is_platform_admin(request.user):
        return redirect("platform-dashboard")

    if request.method == "GET":
        return render(request, "platform_admin/login.html")

    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "")
    user = authenticate(request, username=username, password=password)

    if not user or not user.is_staff:
        messages.error(request, "Invalid platform admin credentials.")
        return render(request, "platform_admin/login.html", status=401)

    login(request, user)
    return redirect("platform-dashboard")


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("platform-login")


@platform_admin_required
@require_http_methods(["GET"])
def dashboard_view(request: HttpRequest) -> HttpResponse:
    context = {
        "company_count": Company.objects.count(),
        "active_company_count": Company.objects.filter(status="active").count(),
        "inactive_company_count": Company.objects.exclude(status="active").count(),
        "company_admin_count": UserAccount.objects.filter(is_company_admin=True).count(),
        "recent_companies": Company.objects.order_by("-created_at")[:5],
    }
    return render(request, "platform_admin/dashboard.html", context)


@platform_admin_required
@require_http_methods(["GET"])
def company_list_view(request: HttpRequest) -> HttpResponse:
    companies = Company.objects.order_by("legal_name")
    return render(request, "platform_admin/company_list.html", {"companies": companies})


@platform_admin_required
@require_http_methods(["GET", "POST"])
def company_create_view(request: HttpRequest) -> HttpResponse:
    form = CompanyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        company = form.save()
        messages.success(request, "Company created successfully.")
        return redirect("platform-company-detail", company_id=company.id)
    return render(request, "platform_admin/company_form.html", {"form": form})


@platform_admin_required
@require_http_methods(["GET"])
def company_detail_view(request: HttpRequest, company_id) -> HttpResponse:
    company = get_object_or_404(Company, id=company_id)
    admins = UserAccount.objects.filter(company=company, is_company_admin=True).select_related("role")
    return render(
        request,
        "platform_admin/company_detail.html",
        {
            "company": company,
            "admins": admins,
        },
    )


@platform_admin_required
@require_POST
def company_activate_view(request: HttpRequest, company_id) -> HttpResponse:
    Company.objects.filter(id=company_id).update(status="active")
    messages.success(request, "Company activated.")
    return redirect("platform-company-detail", company_id=company_id)


@platform_admin_required
@require_POST
def company_deactivate_view(request: HttpRequest, company_id) -> HttpResponse:
    Company.objects.filter(id=company_id).update(status="inactive")
    messages.success(request, "Company deactivated.")
    return redirect("platform-company-detail", company_id=company_id)


@platform_admin_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def first_company_admin_create_view(request: HttpRequest, company_id) -> HttpResponse:
    company = get_object_or_404(Company, id=company_id)
    form = FirstCompanyAdminForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        if UserAccount.objects.filter(company=company, email__iexact=form.cleaned_data["email"]).exists():
            form.add_error("email", "This email is already used in this company.")
            return render(
                request,
                "platform_admin/company_admin_form.html",
                {
                    "company": company,
                    "form": form,
                },
                status=400,
            )

        role, _ = Role.objects.get_or_create(
            company=company,
            name="Company Admin",
            defaults={
                "description": "Default company administrator role.",
                "is_system_role": True,
                "is_active": True,
            },
        )
        user = form.save(commit=False)
        user.company = company
        user.role = role
        user.password = make_password(form.cleaned_data["password"])
        user.is_company_admin = True
        user.is_active = True
        user.save()
        messages.success(request, "Company admin created successfully.")
        return redirect("platform-company-detail", company_id=company.id)

    return render(
        request,
        "platform_admin/company_admin_form.html",
        {
            "company": company,
            "form": form,
        },
    )
