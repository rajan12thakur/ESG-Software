from django.urls import path

from platform_admin import views


urlpatterns = [
    path("login/", views.login_view, name="platform-login"),
    path("logout/", views.logout_view, name="platform-logout"),
    path("dashboard/", views.dashboard_view, name="platform-dashboard"),
    path("companies/", views.company_list_view, name="platform-company-list"),
    path("companies/create/", views.company_create_view, name="platform-company-create"),
    path("companies/<uuid:company_id>/", views.company_detail_view, name="platform-company-detail"),
    path("companies/<uuid:company_id>/activate/", views.company_activate_view, name="platform-company-activate"),
    path("companies/<uuid:company_id>/deactivate/", views.company_deactivate_view, name="platform-company-deactivate"),
    path("companies/<uuid:company_id>/admins/create/", views.first_company_admin_create_view, name="platform-company-admin-create"),
]
