import json

from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView

from accounts.models import UserAccount
from authentication.tokens import create_access_token
from core.models import Company

ACTIVE_COMPANY_STATUS = "active"


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def _normalize_tenant_code(value: str) -> str:
    return value.strip().lower()


def _serialize_role_assignments(user):
    return [
        {
            "id": str(assignment.role_id),
            "name": assignment.role.name,
        }
        for assignment in user.user_roles.select_related("role").filter(
            role__company=user.company,
            role__is_active=True,
        ).order_by("assigned_at", "role__name")
    ]


def _user_response(user):
    return {
        "id": str(user.id),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "company_id": str(user.company_id),
        "tenant_code": user.company.tenant_code,
        "roles": _serialize_role_assignments(user),
        "is_company_admin": user.is_company_admin,
    }


def _authenticate_company_user(tenant_code, email, password):
    normalized_tenant_code = _normalize_tenant_code(tenant_code)
    normalized_email = email.strip().lower()

    try:
        company = Company.objects.get(tenant_code=normalized_tenant_code)
    except Company.DoesNotExist:
        return None, "invalid_tenant_code"

    if company.status != ACTIVE_COMPANY_STATUS:
        return None, "inactive_company"

    try:
        user = UserAccount.objects.select_related("company").get(
            company=company,
            email__iexact=normalized_email,
        )
    except UserAccount.DoesNotExist:
        return None, "invalid_credentials"

    if not check_password(password, user.password):
        return None, "invalid_credentials"

    if not user.is_active:
        return None, "inactive_user"

    return user, None


def _issue_token(user):
    token, expires_at = create_access_token(user)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login", "updated_at"])
    return token, expires_at


def _html_error_message(error_code):
    return {
        "invalid_tenant_code": "Invalid tenant code.",
        "inactive_company": "This company is inactive.",
        "inactive_user": "User account is inactive.",
        "invalid_credentials": "Invalid tenant code, email, or password.",
    }[error_code]


def _json_error_message(error_code):
    return {
        "invalid_tenant_code": "Invalid tenant code.",
        "inactive_company": "This company is inactive.",
        "inactive_user": "User account is inactive.",
        "invalid_credentials": "Invalid tenant code, email, or password.",
    }[error_code]


class CompanyLoginView(TemplateView):
    template_name = "authentication/login.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user_account:
            return redirect("company-dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("tenant_code_value", "")
        context.setdefault("email_value", "")
        return context

    def post(self, request, *args, **kwargs):
        tenant_code = request.POST.get("tenant_code", "")
        email = request.POST.get("email", "")
        password = request.POST.get("password", "")

        context = self.get_context_data(
            tenant_code_value=_normalize_tenant_code(tenant_code),
            email_value=email.strip().lower(),
        )

        if not tenant_code or not email or not password:
            messages.error(request, "Tenant code, email, and password are required.")
            return render(request, self.template_name, context=context, status=400)

        user, error_code = _authenticate_company_user(tenant_code, email, password)
        if error_code:
            messages.error(request, _html_error_message(error_code))
            status_code = 401 if error_code in {"invalid_tenant_code", "invalid_credentials"} else 403
            return render(request, self.template_name, context=context, status=status_code)

        token, expires_at = _issue_token(user)
        response = redirect("company-dashboard")
        response.set_cookie(
            "company_access_token",
            token,
            expires=expires_at,
            httponly=True,
            samesite="Lax",
        )
        return response


class CompanyLoginAPIView(View):
    def post(self, request, *args, **kwargs):
        data = _json_body(request)
        tenant_code = data.get("tenant_code", "")
        email = data.get("email", "")
        password = data.get("password", "")

        if not tenant_code or not email or not password:
            return JsonResponse(
                {"error": "Tenant code, email, and password are required."},
                status=400,
            )

        user, error_code = _authenticate_company_user(tenant_code, email, password)
        if error_code:
            status_code = 401 if error_code in {"invalid_tenant_code", "invalid_credentials"} else 403
            return JsonResponse(
                {"error": _json_error_message(error_code)},
                status=status_code,
            )

        token, expires_at = _issue_token(user)
        return JsonResponse(
            {
                "access_token": token,
                "expires_at": expires_at.isoformat(),
                "user": _user_response(user),
            }
        )


class CompanyMeView(View):
    def get(self, request, *args, **kwargs):
        if not request.user_account:
            return JsonResponse({"error": "Authentication required."}, status=401)
        return JsonResponse({"user": _user_response(request.user_account)})


class CompanyDashboardView(TemplateView):
    template_name = "authentication/dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        if not request.user_account:
            return redirect("company-login")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "user_account": self.request.user_account,
                "company": self.request.company,
                "user_roles": self.request.user_roles,
            }
        )
        return context


class CompanyLogoutView(View):
    def post(self, request, *args, **kwargs):
        response = redirect("company-login")
        response.delete_cookie("company_access_token")
        return response
