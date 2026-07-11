from django import forms
from django.contrib.auth.password_validation import validate_password

from accounts.models import Permission, Role, UserAccount
from core.models import Department


class CompanyRoleForm(forms.ModelForm):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = Role
        fields = ["name", "description", "is_active"]

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["permissions"].queryset = Permission.objects.order_by("module", "name")
        if self.instance.pk:
            self.fields["permissions"].initial = self.instance.role_permissions.values_list("permission_id", flat=True)

    def save_permissions(self):
        from accounts.models import RolePermission
        RolePermission.objects.filter(role=self.instance).exclude(
            permission__in=self.cleaned_data["permissions"]
        ).delete()
        for permission in self.cleaned_data["permissions"]:
            RolePermission.objects.get_or_create(role=self.instance, permission=permission)


class UserAccountCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    departments = forms.ModelMultipleChoiceField(queryset=Department.objects.none(), required=False)

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
        self.fields["departments"].queryset = Department.objects.filter(company=company, is_active=True)

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
    departments = forms.ModelMultipleChoiceField(queryset=Department.objects.none(), required=False)
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
        self.fields["departments"].queryset = Department.objects.filter(company=company, is_active=True)
        if self.instance.pk:
            self.fields["departments"].initial = self.instance.user_departments.values_list("department_id", flat=True)

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
