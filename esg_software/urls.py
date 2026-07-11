from django.contrib import admin
from django.urls import path, include

from core.views import home_view

urlpatterns = [
    path('', home_view, name='home'),
    path('admin/', admin.site.urls),
    path('platform/', include('platform_admin.urls')),
    path('auth/', include('authentication.urls')),
    path('core/', include('core.urls')),
    path('accounts/', include('accounts.urls')),
]
