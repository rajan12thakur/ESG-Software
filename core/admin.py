from django.contrib import admin

from core.models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("legal_name", "display_name", "status", "country", "is_demo_tenant")
    list_filter = ("status", "country", "is_demo_tenant")
    search_fields = ("legal_name", "display_name", "registration_number")
    readonly_fields = ("created_at", "updated_at")
