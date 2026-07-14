from django.urls import path

from authentication import views


urlpatterns = [
    path("login/", views.CompanyLoginView.as_view(), name="company-login"),
    path("login/api/", views.CompanyLoginAPIView.as_view(), name="company-login-api"),
    path("logout/", views.CompanyLogoutView.as_view(), name="company-logout"),
    path("dashboard/", views.CompanyDashboardView.as_view(), name="company-dashboard"),
    path("me/", views.CompanyMeView.as_view(), name="company-me"),
]
