from django.urls import path

from platform_admin import views


urlpatterns = [
    path("login/", views.PlatformLoginView.as_view(), name="platform-login"),
    path("logout/", views.PlatformLogoutView.as_view(), name="platform-logout"),
    path("dashboard/", views.PlatformDashboardView.as_view(), name="platform-dashboard"),
    path("companies/", views.CompanyListView.as_view(), name="platform-company-list"),
    path("companies/create/", views.CompanyCreateView.as_view(), name="platform-company-create"),
    path("companies/<uuid:company_id>/", views.CompanyDetailView.as_view(), name="platform-company-detail"),
    path("companies/<uuid:company_id>/activate/", views.CompanyActivateView.as_view(), name="platform-company-activate"),
    path("companies/<uuid:company_id>/deactivate/", views.CompanyDeactivateView.as_view(), name="platform-company-deactivate"),
    path("companies/<uuid:company_id>/admins/create/", views.FirstCompanyAdminCreateView.as_view(), name="platform-company-admin-create"),
]
