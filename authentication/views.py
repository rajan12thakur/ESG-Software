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


def _json_body(request):
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def _user_response(user):
    return {"id": str(user.id), "first_name": user.first_name, "last_name": user.last_name,
            "email": user.email, "company": str(user.company_id), "role": str(user.role_id),
            "is_company_admin": user.is_company_admin}


def _authenticate_company_user(email, password):
    user = UserAccount.objects.select_related("company", "role").filter(email__iexact=email).first()
    return user if user and check_password(password, user.password) else None


def _issue_token(user):
    token, expires_at = create_access_token(user)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login", "updated_at"])
    return token, expires_at


class CompanyLoginView(TemplateView):
    template_name = "authentication/login.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user_account:
            return redirect("company-dashboard")
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        email, password = request.POST.get("email", "").strip(), request.POST.get("password", "")
        if not email or not password:
            messages.error(request, "Email and password are required.")
            return render(request, self.template_name, status=400)
        user = _authenticate_company_user(email, password)
        if not user:
            messages.error(request, "Invalid email or password.")
            return render(request, self.template_name, status=401)
        if not user.is_active:
            messages.error(request, "User account is inactive.")
            return render(request, self.template_name, status=403)
        token, expires_at = _issue_token(user)
        response = redirect("company-dashboard")
        response.set_cookie("company_access_token", token, expires=expires_at, httponly=True, samesite="Lax")
        return response


class CompanyLoginAPIView(View):
    def post(self, request, *args, **kwargs):
        data = _json_body(request)
        email, password = data.get("email", ""), data.get("password", "")
        if not email or not password:
            return JsonResponse({"error": "Email and password are required."}, status=400)
        user = _authenticate_company_user(email, password)
        if not user:
            return JsonResponse({"error": "Invalid email or password."}, status=401)
        if not user.is_active:
            return JsonResponse({"error": "User account is inactive."}, status=403)
        token, expires_at = _issue_token(user)
        return JsonResponse({"access_token": token, "expires_at": expires_at.isoformat(), "user": _user_response(user)})


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
        context.update({"user_account": self.request.user_account, "company": self.request.company, "role": self.request.role})
        return context


class CompanyLogoutView(View):
    def post(self, request, *args, **kwargs):
        response = redirect("company-login")
        response.delete_cookie("company_access_token")
        return response
