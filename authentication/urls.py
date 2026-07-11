from django.urls import path

from authentication.views import dashboard_view, login_api_view, login_view, logout_view, me_view


urlpatterns = [
    path("login/", login_view, name="company-login"),
    path("login/api/", login_api_view, name="company-login-api"),
    path("logout/", logout_view, name="company-logout"),
    path("dashboard/", dashboard_view, name="company-dashboard"),
    path("me/", me_view, name="company-me"),
]
