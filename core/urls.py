from django.urls import path
from core import views

urlpatterns = [
    path("profile/", views.CompanyProfileView.as_view(), name="company-profile"),
    path("departments/", views.DepartmentListView.as_view(), name="company-department-list"),
    path("departments/create/", views.DepartmentCreateView.as_view(), name="company-department-create"),
    path("departments/<uuid:object_id>/edit/", views.DepartmentUpdateView.as_view(), name="company-department-update"),
    path("organization-units/", views.OrganizationUnitListView.as_view(), name="company-unit-list"),
    path("organization-units/create/", views.OrganizationUnitCreateView.as_view(), name="company-unit-create"),
    path("organization-units/<uuid:object_id>/edit/", views.OrganizationUnitUpdateView.as_view(), name="company-unit-update"),
    path("organization-units/<uuid:unit_id>/facilities/", views.UnitFacilityListView.as_view(), name="company-unit-facility-list"),
    path("organization-units/<uuid:unit_id>/facilities/create/", views.UnitFacilityCreateView.as_view(), name="company-unit-facility-create"),
    path("organization-units/<uuid:unit_id>/facilities/<uuid:object_id>/edit/", views.UnitFacilityUpdateView.as_view(), name="company-unit-facility-update"),
]
