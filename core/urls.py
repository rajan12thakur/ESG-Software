from django.urls import path
from core import views

urlpatterns = [
    path("profile/", views.profile_view, name="company-profile"),
    path("departments/", views.department_list_view, name="company-department-list"),
    path("departments/create/", views.department_create_view, name="company-department-create"),
    path("departments/<uuid:object_id>/edit/", views.department_update_view, name="company-department-update"),
    path("organization-units/", views.unit_list_view, name="company-unit-list"),
    path("organization-units/create/", views.unit_create_view, name="company-unit-create"),
    path("organization-units/<uuid:object_id>/edit/", views.unit_update_view, name="company-unit-update"),
    path("facilities/", views.facility_list_view, name="company-facility-list"),
    path("facilities/create/", views.facility_create_view, name="company-facility-create"),
    path("facilities/<uuid:object_id>/edit/", views.facility_update_view, name="company-facility-update"),
]
