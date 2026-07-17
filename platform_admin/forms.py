from django import forms
from django.contrib.auth.password_validation import validate_password
from zoneinfo import available_timezones

from accounts.models import Role, UserAccount
from core.models import Company

TIMEZONE_CHOICES = sorted(
    [(tz, tz) for tz in available_timezones()],
    key=lambda x: x[0]
)

CURRENCY_CHOICES = [
    ("", "Select currency"),
    ("INR", "INR"),
    ("USD", "USD"),
    ("EUR", "EUR"),
    ("GBP", "GBP"),
    ("AED", "AED"),
    ("SGD", "SGD"),
    ("JPY", "JPY"),
]

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
        widgets = {
            "legal_name": forms.TextInput(attrs={"placeholder": "Enter legal company name"}),
            "display_name": forms.TextInput(attrs={"placeholder": "Enter display name"}),
            "tenant_code": forms.TextInput(attrs={"placeholder": "Enter tenant code"}),
            "registration_number": forms.TextInput(attrs={"placeholder": "Enter registration number"}),
            "industry": forms.TextInput(attrs={"placeholder": "Enter industry"}),
            "country": forms.TextInput(attrs={"placeholder": "Enter country"}),
            "currency": forms.Select(choices=CURRENCY_CHOICES),
            "timezone": forms.Select(
                choices=TIMEZONE_CHOICES,
                attrs={"placeholder": "Select timezone"}
            ),
            "status": forms.Select(),
        }

    def clean_tenant_code(self):
        return self.cleaned_data["tenant_code"].strip().lower()


class FirstCompanyAdminForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"placeholder": "Enter password"},
        )
    )

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
        widgets = {
            "employee_code": forms.TextInput(attrs={"placeholder": "Enter employee code"}),
            "first_name": forms.TextInput(attrs={"placeholder": "Enter first name"}),
            "last_name": forms.TextInput(attrs={"placeholder": "Enter last name"}),
            "email": forms.EmailInput(attrs={"placeholder": "Enter email address"}),
            "phone": forms.TelInput(attrs={"placeholder": "Enter phone number"}),
        }

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password


# class RoleForm(forms.ModelForm):
#     class Meta:
#         model = Role
#         fields = ["name", "description", "is_system_role", "is_active"]
