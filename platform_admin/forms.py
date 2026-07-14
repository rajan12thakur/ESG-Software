from django import forms
from django.contrib.auth.password_validation import validate_password

from accounts.models import Role, UserAccount
from core.models import Company


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = [
            "legal_name",
            "display_name",
            "tenant_code",
            "registration_number",
            "industry",
            "country",
            "currency",
            "timezone",
            "status",
            "is_demo_tenant",
        ]

    def clean_tenant_code(self):
        return self.cleaned_data["tenant_code"].strip().lower()


class FirstCompanyAdminForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = UserAccount
        fields = [
            "employee_code",
            "first_name",
            "last_name",
            "email",
            "phone",
            "password",
        ]

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password


class RoleForm(forms.ModelForm):
    class Meta:
        model = Role
        fields = ["name", "description", "is_system_role", "is_active"]
