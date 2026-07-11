from django.http import JsonResponse

from accounts.models import UserAccount
from authentication.tokens import TokenError, decode_access_token


class JWTAuthenticationMiddleware:
    """Attach company-user JWT context to request when a Bearer token exists."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user_account = None
        request.company = None
        request.role = None
        request.is_company_admin = False

        header = request.headers.get("Authorization", "")
        token = request.COOKIES.get("company_access_token", "")

        if header:
            if not header.startswith("Bearer "):
                return JsonResponse({"error": "Invalid Authorization header."}, status=401)
            token = header.removeprefix("Bearer ").strip()

        if not token:
            return self.get_response(request)

        try:
            payload = decode_access_token(token)
            user = UserAccount.objects.select_related("company", "role").get(
                id=payload["user_id"],
                company_id=payload["company_id"],
                role_id=payload["role_id"],
            )
        except (KeyError, UserAccount.DoesNotExist, TokenError):
            return JsonResponse({"error": "Invalid or expired token."}, status=401)

        if not user.is_active:
            return JsonResponse({"error": "User account is inactive."}, status=403)

        request.user_account = user
        request.company = user.company
        request.role = user.role
        request.is_company_admin = user.is_company_admin
        return self.get_response(request)
