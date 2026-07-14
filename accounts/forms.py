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

    def clean_name(self):
        name = self.cleaned_data["name"].strip()

        queryset = Role.objects.filter(
            company=self.company,
            name__iexact=name,
        )

        # Ignore current role while editing
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)

        if queryset.exists():
            raise forms.ValidationError(
                "A role with this name already exists."
            )

        return name

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


class PermissionDefinitionForm(forms.Form):
    ACTIONS = ("View", "Create", "Edit", "Delete", "Update")

    model_name = forms.CharField(
        max_length=150,
        help_text="Use a clear plural name, such as Projects or ESG Data.",
    )
    actions = forms.MultipleChoiceField(
        choices=[(action.lower(), action) for action in ACTIONS],
        initial=[action.lower() for action in ACTIONS],
        widget=forms.CheckboxSelectMultiple,
    )

    def clean_model_name(self):
        return " ".join(self.cleaned_data["model_name"].split())

    def save(self):
        model_name = self.cleaned_data["model_name"]
        slug = model_name.lower().replace(" ", "_")
        for action in self.cleaned_data["actions"]:
            Permission.objects.get_or_create(
                code=f"{slug}.{action}",
                defaults={"name": f"{action.title()} {model_name}", "module": model_name},
            )


class UserAccountCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)
    department = forms.ModelChoiceField(queryset=Department.objects.none(), required=False, empty_label="Select a department")
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Select the actions this user can perform. Permissions are grouped by module.",
    )

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
            "is_active",
        ]

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["role"].queryset = Role.objects.filter(company=company, is_active=True, is_system_role = False)
        self.fields["department"].queryset = Department.objects.filter(company=company, is_active=True).order_by("name")
        self.fields["permissions"].queryset = Permission.objects.order_by("module", "name")

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
    department = forms.ModelChoiceField(queryset=Department.objects.none(), required=False, empty_label="Select a department")
    permissions = forms.ModelMultipleChoiceField(queryset=Permission.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    class Meta:
        model = UserAccount
        fields = [
            "role",
            "employee_code",
            "first_name",
            "last_name",
            "email",
            "phone",
            "is_active",
        ]

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.company = company
        self.fields["role"].queryset = Role.objects.filter(company=company, is_active=True)
        self.fields["department"].queryset = Department.objects.filter(company=company, is_active=True).order_by("name")
        self.fields["permissions"].queryset = Permission.objects.order_by("module", "name")
        if self.instance.pk:
            self.fields["department"].initial = self.instance.user_departments.values_list("department_id", flat=True).first()
            self.fields["permissions"].initial = self.instance.user_permissions.values_list("permission_id", flat=True)

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
