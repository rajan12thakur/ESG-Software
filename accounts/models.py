import uuid

from django.db import models

from core.models import Company, Department


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="roles",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_system_role = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"],
                name="unique_role_name_per_company",
            )
        ]

    def __str__(self) -> str:
        return self.name


class Permission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=150, unique=True)
    name = models.CharField(max_length=255)
    module = models.CharField(max_length=150, blank=True)
    description = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.code


class UserAccount(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="user_accounts",
    )
    employee_code = models.CharField(max_length=100, blank=True)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True)
    password = models.CharField(max_length=255)
    is_company_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["company", "email"],
                name="unique_user_account_email_per_company",
            ),
            models.UniqueConstraint(
                fields=["company"],
                condition=models.Q(is_company_admin=True),
                name="one_company_admin_per_company",
            ),
        ]

    def __str__(self) -> str:
        return self.email

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class UserRole(models.Model):
    """Links a user to a role."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        UserAccount,
        on_delete=models.CASCADE,
        related_name="user_roles",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="user_roles",
    )
    assigned_by = models.ForeignKey(
        UserAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_roles",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "role"],
                name="unique_user_role_assignment",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.role}"


class UserRoleScope(models.Model):
    """Stores scopes for one role assignment."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_role = models.ForeignKey(
        UserRole,
        on_delete=models.CASCADE,
        related_name="scopes",
    )
    scope_type = models.CharField(max_length=100)
    scope_id = models.UUIDField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user_role", "scope_type", "scope_id"],
                name="unique_user_role_scope_row",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user_role} [{self.scope_type}]"


class RolePermission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )

    def __str__(self) -> str:
        return f"{self.role} -> {self.permission}"


class UserDepartment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        UserAccount,
        on_delete=models.CASCADE,
        related_name="user_departments",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="user_departments",
    )

    def __str__(self) -> str:
        return f"{self.user} -> {self.department}"
