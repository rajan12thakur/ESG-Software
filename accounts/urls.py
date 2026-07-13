from django.urls import path

from accounts import views


urlpatterns = [
    path("users/", views.UserListView.as_view(), name="account-user-list"),
    path("users/create/", views.UserCreateView.as_view(), name="account-user-create"),
    path("users/<uuid:user_id>/", views.UserDetailView.as_view(), name="account-user-detail"),
    path("users/<uuid:user_id>/edit/", views.UserUpdateView.as_view(), name="account-user-update"),
    path("users/<uuid:user_id>/activate/", views.UserActivateView.as_view(), name="account-user-activate"),
    path("users/<uuid:user_id>/deactivate/", views.UserDeactivateView.as_view(), name="account-user-deactivate"),
    path("roles/", views.RoleListView.as_view(), name="account-role-list"),
    path("roles/create/", views.RoleCreateView.as_view(), name="account-role-create"),
    path("roles/<uuid:role_id>/edit/", views.RoleUpdateView.as_view(), name="account-role-update"),
    path("roles/<uuid:role_id>/permissions/", views.RolePermissionMatrixView.as_view(), name="account-role-permissions"),
    path("permissions/create/", views.PermissionCreateView.as_view(), name="account-permission-create"),
]
