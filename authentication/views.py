import json

from django.contrib import messages
from django.contrib.auth.hashers import check_password
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.models import UserAccount
from authentication.tokens import create_access_token


def _json_body(request: HttpRequest) -> dict:
    try:
        return json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {}


def _user_response(user: UserAccount) -> dict:
    return {
        "id": str(user.id),
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "company": str(user.company_id),
        "role": str(user.role_id),
        "is_company_admin": user.is_company_admin,
    }


def _authenticate_company_user(email: str, password: str) -> UserAccount | None:
    user = UserAccount.objects.select_related("company", "role").filter(email__iexact=email).first()
    if not user or not check_password(password, user.password):
        return None
    return user


@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    if request.user_account:
        return redirect("company-dashboard")

    if request.method == "GET":
        return render(request, "authentication/login.html")

    email = request.POST.get("email", "").strip()
    password = request.POST.get("password", "")

    if not email or not password:
        messages.error(request, "Email and password are required.")
        return render(request, "authentication/login.html", status=400)

    user = _authenticate_company_user(email, password)
    if not user:
        messages.error(request, "Invalid email or password.")
        return render(request, "authentication/login.html", status=401)

    if not user.is_active:
        messages.error(request, "User account is inactive.")
        return render(request, "authentication/login.html", status=403)

    token, expires_at = create_access_token(user)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login", "updated_at"])

    response = redirect("company-dashboard")
    response.set_cookie(
        "company_access_token",
        token,
        expires=expires_at,
        httponly=True,
        samesite="Lax",
    )
    return response


@require_http_methods(["POST"])
def login_api_view(request: HttpRequest) -> JsonResponse:
    data = _json_body(request)
    email = data.get("email", "")
    password = data.get("password", "")

    if not email or not password:
        return JsonResponse({"error": "Email and password are required."}, status=400)

    user = _authenticate_company_user(email, password)
    if not user:
        return JsonResponse({"error": "Invalid email or password."}, status=401)

    if not user.is_active:
        return JsonResponse({"error": "User account is inactive."}, status=403)

    token, expires_at = create_access_token(user)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login", "updated_at"])

    return JsonResponse(
        {
            "access_token": token,
            "expires_at": expires_at.isoformat(),
            "user": _user_response(user),
        }
    )


@require_http_methods(["GET"])
def me_view(request: HttpRequest) -> JsonResponse:
    if not request.user_account:
        return JsonResponse({"error": "Authentication required."}, status=401)
    return JsonResponse({"user": _user_response(request.user_account)})


@require_http_methods(["GET"])
def dashboard_view(request: HttpRequest) -> HttpResponse:
    if not request.user_account:
        return redirect("company-login")
    return render(
        request,
        "authentication/dashboard.html",
        {
            "user_account": request.user_account,
            "company": request.company,
            "role": request.role,
        },
    )


@require_http_methods(["POST"])
def logout_view(request: HttpRequest) -> HttpResponse:
    response = redirect("company-login")
    response.delete_cookie("company_access_token")
    return response
