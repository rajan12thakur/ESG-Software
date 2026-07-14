from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import make_password
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import DetailView, FormView, ListView, TemplateView

from accounts.models import Role, UserAccount, UserRole
from core.models import Company
from platform_admin.forms import CompanyForm, FirstCompanyAdminForm


class PlatformAdminRequiredMixin(UserPassesTestMixin):
    login_url = "platform-login"

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

    def handle_no_permission(self):
        return redirect(self.login_url)


class PlatformLoginView(TemplateView):
    template_name = "platform_admin/login.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_staff:
            return redirect("platform-dashboard")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        user = authenticate(request, username=request.POST.get("username", "").strip(), password=request.POST.get("password", ""))
        if not user or not user.is_staff:
            messages.error(request, "Invalid platform admin credentials.")
            return render(request, self.template_name, status=401)
        login(request, user)
        return redirect("platform-dashboard")


class PlatformLogoutView(View):
    def post(self, request, *args, **kwargs):
        logout(request)
        return redirect("platform-login")


class PlatformDashboardView(PlatformAdminRequiredMixin, TemplateView):
    template_name = "platform_admin/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({"company_count": Company.objects.count(), "active_company_count": Company.objects.filter(status="active").count(),
                        "inactive_company_count": Company.objects.exclude(status="active").count(), "company_admin_count": UserAccount.objects.filter(is_company_admin=True).count(),
                        "recent_companies": Company.objects.order_by("-created_at")[:5]})
        return context


class CompanyListView(PlatformAdminRequiredMixin, ListView):
    template_name = "platform_admin/company_list.html"
    context_object_name = "companies"
    queryset = Company.objects.order_by("legal_name")


class CompanyCreateView(PlatformAdminRequiredMixin, FormView):
    template_name = "platform_admin/company_form.html"
    form_class = CompanyForm

    def form_valid(self, form):
        company = form.save()
        messages.success(self.request, "Company created successfully.")
        return redirect("platform-company-detail", company_id=company.id)


class CompanyDetailView(PlatformAdminRequiredMixin, DetailView):
    template_name = "platform_admin/company_detail.html"
    context_object_name = "company"

    def get_object(self, queryset=None):
        return get_object_or_404(Company, id=self.kwargs["company_id"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["admins"] = UserAccount.objects.filter(
            company=self.object,
            is_company_admin=True,
        ).prefetch_related("user_roles__role")
        return context


class CompanyStatusView(PlatformAdminRequiredMixin, View):
    status = "active"

    def post(self, request, company_id, *args, **kwargs):
        Company.objects.filter(id=company_id).update(status=self.status)
        messages.success(request, "Company activated." if self.status == "active" else "Company deactivated.")
        return redirect("platform-company-detail", company_id=company_id)


class CompanyActivateView(CompanyStatusView):
    status = "active"


class CompanyDeactivateView(CompanyStatusView):
    status = "inactive"


class FirstCompanyAdminCreateView(PlatformAdminRequiredMixin, FormView):
    template_name = "platform_admin/company_admin_form.html"
    form_class = FirstCompanyAdminForm

    def get_company(self):
        return get_object_or_404(Company, id=self.kwargs["company_id"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["company"] = self.get_company()
        return context

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        return response

    def get(self, request, *args, **kwargs):
        company = self.get_company()
        if UserAccount.objects.filter(company=company, is_company_admin=True).exists():
            messages.error(request, "This company already has a company admin.")
            return redirect("platform-company-detail", company_id=company.id)
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        company = self.get_company()
        if UserAccount.objects.filter(company=company, is_company_admin=True).exists():
            messages.error(request, "This company already has a company admin.")
            return redirect("platform-company-detail", company_id=company.id)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        company = self.get_company()
        if UserAccount.objects.filter(company=company, email__iexact=form.cleaned_data["email"]).exists():
            form.add_error("email", "This email is already used in this company.")
            return self.form_invalid(form)
        with transaction.atomic():
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
            user.password = make_password(form.cleaned_data["password"])
            user.is_company_admin, user.is_active = True, True
            user.save()
            UserRole.objects.get_or_create(user=user, role=role)
        messages.success(self.request, "Company admin created successfully.")
        return redirect("platform-company-detail", company_id=company.id)
