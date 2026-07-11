from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('platform/', include('platform_admin.urls')),
    path('auth/', include('authentication.urls')),
    path('core/', include('core.urls')),
    path('accounts/', include('accounts.urls')),
]
