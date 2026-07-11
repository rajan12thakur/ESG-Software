from django import forms
from django.contrib.auth.password_validation import validate_password

from accounts.models import Role, UserAccount


class UserAccountCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = UserAccount
        fields = [
            "role",
            "employee_code",
            "first_name",
            "last_name",
            "email",
            "phone",
            "password",
            "is_company_admin",
            "is_active",
        ]

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["role"].queryset = Role.objects.filter(company=company, is_active=True)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if UserAccount.objects.filter(company=self.company, email__iexact=email).exists():
            raise forms.ValidationError("This email is already used in this company.")
        return email

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password


class UserAccountUpdateForm(forms.ModelForm):
    class Meta:
        model = UserAccount
        fields = [
            "role",
            "employee_code",
            "first_name",
            "last_name",
            "email",
            "phone",
            "is_company_admin",
            "is_active",
        ]

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["role"].queryset = Role.objects.filter(company=company, is_active=True)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        exists = (
            UserAccount.objects.filter(company=self.company, email__iexact=email)
            .exclude(pk=self.instance.pk)
            .exists()
        )
        if exists:
            raise forms.ValidationError("This email is already used in this company.")
        return email
