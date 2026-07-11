from django.urls import path

from accounts import views


urlpatterns = [
    path("users/", views.user_list_view, name="account-user-list"),
    path("users/create/", views.user_create_view, name="account-user-create"),
    path("users/<uuid:user_id>/", views.user_detail_view, name="account-user-detail"),
    path("users/<uuid:user_id>/edit/", views.user_update_view, name="account-user-update"),
    path("users/<uuid:user_id>/activate/", views.user_activate_view, name="account-user-activate"),
    path("users/<uuid:user_id>/deactivate/", views.user_deactivate_view, name="account-user-deactivate"),
]
