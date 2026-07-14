import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, connection, transaction
from django.http import HttpResponse, JsonResponse
from django.test import TestCase, override_settings
from django.urls import include, path
from django.views import View

from accounts import models as account_models
from accounts.mixins import RolePermissionMixin
from accounts.models import Permission, Role, RolePermission, UserAccount, UserRole, UserRoleScope
from accounts.permission_catalog import (
    CANONICAL_PERMISSION_CODES,
    CANONICAL_PERMISSION_SPECS,
    get_permission_map,
    sync_permission_catalog,
)
from accounts.rbac import (
    ResourceContext,
    authorize,
    get_active_user_role_assignments,
)
from authentication.tokens import create_access_token, decode_access_token
from core.models import Company, Department, Facility, OrganizationUnit


class PermissionProtectedView(RolePermissionMixin, View):
    required_permission = "users.view"

    def get(self, request, *args, **kwargs):
        return HttpResponse("ok")


class AdminProtectedView(RolePermissionMixin, View):
    required_permission = "roles.view"

    def get(self, request, *args, **kwargs):
        return HttpResponse("ok")


class AuthEchoView(View):
    def get(self, request, *args, **kwargs):
        return JsonResponse(
            {
                "user_id": str(request.user_account.id) if request.user_account else None,
                "company_id": str(request.company.id) if request.company else None,
                "tenant_code": request.company.tenant_code if request.company else None,
                "assigned_role_ids": [
                    str(assignment.role_id)
                    for assignment in getattr(request, "user_roles", ())
                ],
                "is_company_admin": request.is_company_admin,
            }
        )


urlpatterns = [
    path("auth/", include("authentication.urls")),
    path("accounts/", include("accounts.urls")),
    path("core/", include("core.urls")),
    path("platform/", include("platform_admin.urls")),
    path("test/protected/users/", PermissionProtectedView.as_view(), name="test-protected-users"),
    path("test/protected/admin/", AdminProtectedView.as_view(), name="test-protected-admin"),
    path("test/auth-echo/", AuthEchoView.as_view(), name="test-auth-echo"),
]


class SchemaStateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            legal_name="Acme Industries",
            tenant_code="acme-industries",
        )
        cls.other_company = Company.objects.create(
            legal_name="Bravo Holdings",
            tenant_code="bravo-holdings",
        )
        cls.role = Role.objects.create(company=cls.company, name="Manager")
        cls.user = UserAccount.objects.create(
            company=cls.company,
            first_name="Casey",
            last_name="Smith",
            email="casey@example.com",
            password="hashed-password",
        )

    def test_role_name_is_unique_within_company(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Role.objects.create(company=self.company, name=self.role.name)

        duplicate_name_other_company = Role.objects.create(
            company=self.other_company,
            name=self.role.name,
        )

        self.assertEqual(duplicate_name_other_company.name, self.role.name)

    def test_user_role_is_unique_per_user_and_role(self):
        UserRole.objects.create(user=self.user, role=self.role)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserRole.objects.create(user=self.user, role=self.role)

    def test_duplicate_user_role_scope_row_is_rejected(self):
        assignment = UserRole.objects.create(user=self.user, role=self.role)
        scope_id = uuid.uuid4()

        UserRoleScope.objects.create(
            user_role=assignment,
            scope_type="ORG_UNIT",
            scope_id=scope_id,
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                UserRoleScope.objects.create(
                    user_role=assignment,
                    scope_type="ORG_UNIT",
                    scope_id=scope_id,
                )

    def test_removed_legacy_structures_are_absent(self):
        self.assertNotIn("role", [field.name for field in UserAccount._meta.get_fields()])
        self.assertFalse(hasattr(account_models, "UserPermission"))
        self.assertFalse(hasattr(account_models, "RolePermissionScope"))
        self.assertNotIn("accounts_userpermission", connection.introspection.table_names())
        self.assertNotIn("accounts_rolepermissionscope", connection.introspection.table_names())


class PermissionCatalogSeedTests(TestCase):
    def test_fresh_database_contains_expected_permission_catalog(self):
        self.assertEqual(Permission.objects.count(), len(CANONICAL_PERMISSION_CODES))
        self.assertEqual(
            list(Permission.objects.order_by("code").values_list("code", "name", "module")),
            sorted(
                [
                    (spec.code, spec.name, spec.module)
                    for spec in CANONICAL_PERMISSION_SPECS
                ]
            ),
        )

    def test_repeated_seed_execution_does_not_create_duplicates(self):
        first_codes = list(Permission.objects.order_by("code").values_list("code", flat=True))

        sync_permission_catalog()
        sync_permission_catalog()

        self.assertEqual(Permission.objects.count(), len(CANONICAL_PERMISSION_CODES))
        self.assertEqual(
            list(Permission.objects.order_by("code").values_list("code", flat=True)),
            first_codes,
        )


@override_settings(ROOT_URLCONF="accounts.tests")
class PermissionCatalogWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            legal_name="Permission Tenant",
            tenant_code="permission-tenant",
            status="active",
        )
        permissions = get_permission_map(["roles.edit", "roles.update", "users.view"])

        cls.permission_admin_role = Role.objects.create(
            company=cls.company,
            name="Permission Manager",
        )
        cls.target_role = Role.objects.create(
            company=cls.company,
            name="Target Role",
        )
        for code in ("roles.edit", "roles.update"):
            RolePermission.objects.create(
                role=cls.permission_admin_role,
                permission=permissions[code],
            )

        cls.user = UserAccount.objects.create(
            company=cls.company,
            first_name="Pat",
            last_name="Manager",
            email="pat.manager@example.com",
            password=make_password("secret123"),
            is_active=True,
        )
        UserRole.objects.create(user=cls.user, role=cls.permission_admin_role)
        cls.users_view_permission = permissions["users.view"]

    def auth_headers(self, user):
        token, _ = create_access_token(user)
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_role_permission_assignment_uses_seeded_catalog(self):
        response = self.client.post(
            f"/accounts/roles/{self.target_role.id}/permissions/",
            {"permissions": [str(self.users_view_permission.id)]},
            **self.auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            RolePermission.objects.filter(
                role=self.target_role,
                permission=self.users_view_permission,
            ).exists()
        )

    def test_tenant_users_cannot_create_global_permissions(self):
        response = self.client.get(
            "/accounts/permissions/create/",
            **self.auth_headers(self.user),
        )

        self.assertEqual(response.status_code, 404)


class ScopeResolutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            legal_name="Scoped Co",
            tenant_code="scoped-co",
        )
        cls.primary_role = Role.objects.create(company=cls.company, name="Primary Role")
        cls.secondary_role = Role.objects.create(company=cls.company, name="Secondary Role")
        cls.inactive_role = Role.objects.create(
            company=cls.company,
            name="Inactive Role",
            is_active=False,
        )
        cls.permission = get_permission_map(["facilities.view"])["facilities.view"]

    def create_user(self, email, *, is_company_admin=False):
        return UserAccount.objects.create(
            company=self.company,
            first_name="Scoped",
            last_name="User",
            email=email,
            password=make_password("secret123"),
            is_company_admin=is_company_admin,
            is_active=True,
        )

    def test_unrestricted_role_assignment_allows_access(self):
        user = self.create_user("unrestricted@example.com")
        assignment = UserRole.objects.create(user=user, role=self.primary_role)
        RolePermission.objects.create(role=self.primary_role, permission=self.permission)

        self.assertTrue(authorize(user, self.permission.code))
        self.assertEqual(assignment.role, self.primary_role)

    def test_same_scope_type_one_matching_value_allows_access(self):
        user = self.create_user("or-allow@example.com")
        assignment = UserRole.objects.create(user=user, role=self.primary_role)
        RolePermission.objects.create(role=self.primary_role, permission=self.permission)
        matching_id = uuid.uuid4()

        UserRoleScope.objects.create(
            user_role=assignment,
            scope_type="FACILITY",
            scope_id=matching_id,
        )
        UserRoleScope.objects.create(
            user_role=assignment,
            scope_type="FACILITY",
            scope_id=uuid.uuid4(),
        )

        self.assertTrue(
            authorize(
                user,
                self.permission.code,
                ResourceContext.from_mapping({"facility": [matching_id]}),
            )
        )

    def test_same_scope_type_no_matching_value_denies_access(self):
        user = self.create_user("or-deny@example.com")
        assignment = UserRole.objects.create(user=user, role=self.primary_role)
        RolePermission.objects.create(role=self.primary_role, permission=self.permission)

        UserRoleScope.objects.create(
            user_role=assignment,
            scope_type="FACILITY",
            scope_id=uuid.uuid4(),
        )
        UserRoleScope.objects.create(
            user_role=assignment,
            scope_type="FACILITY",
            scope_id=uuid.uuid4(),
        )

        self.assertFalse(
            authorize(
                user,
                self.permission.code,
                ResourceContext.from_mapping({"facility": [uuid.uuid4()]}),
            )
        )

    def test_different_scope_types_all_groups_matching_allows_access(self):
        user = self.create_user("and-allow@example.com")
        assignment = UserRole.objects.create(user=user, role=self.primary_role)
        RolePermission.objects.create(role=self.primary_role, permission=self.permission)
        facility_id = uuid.uuid4()
        org_unit_id = uuid.uuid4()

        UserRoleScope.objects.create(
            user_role=assignment,
            scope_type="FACILITY",
            scope_id=facility_id,
        )
        UserRoleScope.objects.create(
            user_role=assignment,
            scope_type="ORG_UNIT",
            scope_id=org_unit_id,
        )

        self.assertTrue(
            authorize(
                user,
                self.permission.code,
                ResourceContext.from_mapping(
                    {
                        "facility": [facility_id],
                        "org_unit": [org_unit_id],
                    }
                ),
            )
        )

    def test_different_scope_types_missing_or_mismatching_group_denies_access(self):
        user = self.create_user("and-deny@example.com")
        assignment = UserRole.objects.create(user=user, role=self.primary_role)
        RolePermission.objects.create(role=self.primary_role, permission=self.permission)
        facility_id = uuid.uuid4()
        org_unit_id = uuid.uuid4()

        UserRoleScope.objects.create(
            user_role=assignment,
            scope_type="FACILITY",
            scope_id=facility_id,
        )
        UserRoleScope.objects.create(
            user_role=assignment,
            scope_type="ORG_UNIT",
            scope_id=org_unit_id,
        )

        self.assertFalse(
            authorize(
                user,
                self.permission.code,
                ResourceContext.from_mapping({"facility": [facility_id]}),
            )
        )
        self.assertFalse(
            authorize(
                user,
                self.permission.code,
                ResourceContext.from_mapping(
                    {
                        "facility": [facility_id],
                        "org_unit": [uuid.uuid4()],
                    }
                ),
            )
        )

    def test_permission_granted_through_second_role_assignment(self):
        user = self.create_user("second-role@example.com")
        UserRole.objects.create(user=user, role=self.primary_role)
        UserRole.objects.create(user=user, role=self.secondary_role)
        RolePermission.objects.create(role=self.secondary_role, permission=self.permission)

        self.assertTrue(authorize(user, self.permission.code))

    def test_inactive_roles_are_ignored(self):
        user = self.create_user("inactive-scope@example.com")
        UserRole.objects.create(user=user, role=self.inactive_role)
        RolePermission.objects.create(role=self.inactive_role, permission=self.permission)

        self.assertFalse(authorize(user, self.permission.code))

    def test_role_without_required_permission_is_denied(self):
        user = self.create_user("no-permission@example.com")
        UserRole.objects.create(user=user, role=self.primary_role)

        self.assertFalse(authorize(user, self.permission.code))

    def test_company_admin_bypass(self):
        user = self.create_user("company-admin@example.com", is_company_admin=True)

        self.assertTrue(
            authorize(
                user,
                self.permission.code,
                ResourceContext.from_mapping({"facility": [uuid.uuid4()]}),
                is_company_admin=True,
            )
        )


@override_settings(ROOT_URLCONF="accounts.tests")
class TenantIdentityAuthenticationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alpha_company = Company.objects.create(
            legal_name="Alpha Co",
            tenant_code="alpha-co",
            status="active",
        )
        cls.beta_company = Company.objects.create(
            legal_name="Beta Co",
            tenant_code="beta-co",
            status="active",
        )
        cls.inactive_company = Company.objects.create(
            legal_name="Dormant Co",
            tenant_code="dormant-co",
            status="inactive",
        )
        cls.role = Role.objects.create(company=cls.alpha_company, name="Tenant Role")
        cls.beta_role = Role.objects.create(company=cls.beta_company, name="Beta Role")
        cls.inactive_company_role = Role.objects.create(
            company=cls.inactive_company,
            name="Dormant Role",
        )

        cls.alpha_user = UserAccount.objects.create(
            company=cls.alpha_company,
            first_name="Shared",
            last_name="Alpha",
            email="shared@example.com",
            password=make_password("AlphaSecret123!"),
            is_active=True,
        )
        cls.beta_user = UserAccount.objects.create(
            company=cls.beta_company,
            first_name="Shared",
            last_name="Beta",
            email="shared@example.com",
            password=make_password("BetaSecret123!"),
            is_active=True,
        )
        cls.inactive_user = UserAccount.objects.create(
            company=cls.alpha_company,
            first_name="Inactive",
            last_name="User",
            email="inactive@example.com",
            password=make_password("InactiveSecret123!"),
            is_active=False,
        )
        cls.inactive_company_user = UserAccount.objects.create(
            company=cls.inactive_company,
            first_name="Dormant",
            last_name="User",
            email="dormant@example.com",
            password=make_password("DormantSecret123!"),
            is_active=True,
        )

        UserRole.objects.create(user=cls.alpha_user, role=cls.role)
        UserRole.objects.create(user=cls.beta_user, role=cls.beta_role)
        UserRole.objects.create(user=cls.inactive_company_user, role=cls.inactive_company_role)

    def test_same_email_can_exist_in_two_companies(self):
        self.assertEqual(
            UserAccount.objects.filter(email="shared@example.com").count(),
            2,
        )

    def test_tenant_code_selects_the_correct_company_for_html_login(self):
        response = self.client.post(
            "/auth/login/",
            {
                "tenant_code": "beta-co",
                "email": "shared@example.com",
                "password": "BetaSecret123!",
            },
        )
        auth_echo = self.client.get("/test/auth-echo/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/auth/dashboard/")
        self.assertEqual(auth_echo.status_code, 200)
        self.assertEqual(auth_echo.json()["company_id"], str(self.beta_company.id))
        self.assertEqual(auth_echo.json()["tenant_code"], "beta-co")

    def test_invalid_tenant_code_is_rejected(self):
        response = self.client.post(
            "/auth/login/",
            {
                "tenant_code": "missing-tenant",
                "email": "shared@example.com",
                "password": "AlphaSecret123!",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("Invalid tenant code.", response.content.decode())

    def test_inactive_company_is_rejected(self):
        response = self.client.post(
            "/auth/login/",
            {
                "tenant_code": "dormant-co",
                "email": "dormant@example.com",
                "password": "DormantSecret123!",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("This company is inactive.", response.content.decode())

    def test_inactive_user_is_rejected(self):
        response = self.client.post(
            "/auth/login/",
            {
                "tenant_code": "alpha-co",
                "email": "inactive@example.com",
                "password": "InactiveSecret123!",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("User account is inactive.", response.content.decode())

    def test_cross_tenant_login_rejection(self):
        response = self.client.post(
            "/auth/login/",
            {
                "tenant_code": "alpha-co",
                "email": "shared@example.com",
                "password": "BetaSecret123!",
            },
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn(
            "Invalid tenant code, email, or password.",
            response.content.decode(),
        )

    def test_valid_json_login(self):
        response = self.client.post(
            "/auth/login/api/",
            data='{"tenant_code":"alpha-co","email":"shared@example.com","password":"AlphaSecret123!"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["tenant_code"], "alpha-co")
        self.assertNotIn("role", response.json()["user"])
        self.assertEqual(
            response.json()["user"]["roles"],
            [{"id": str(self.role.id), "name": self.role.name}],
        )

    def test_jwt_middleware_restores_correct_company_and_user(self):
        token, _ = create_access_token(self.alpha_user)

        response = self.client.get(
            "/test/auth-echo/",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user_id"], str(self.alpha_user.id))
        self.assertEqual(response.json()["company_id"], str(self.alpha_company.id))
        self.assertEqual(response.json()["assigned_role_ids"], [str(self.role.id)])


@override_settings(ROOT_URLCONF="accounts.tests")
class TenantRuntimeRBACTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            legal_name="Tenant Co",
            tenant_code="tenant-co",
        )
        cls.primary_role = Role.objects.create(company=cls.company, name="Primary Role")
        cls.secondary_role = Role.objects.create(company=cls.company, name="Secondary Role")
        cls.inactive_role = Role.objects.create(
            company=cls.company,
            name="Inactive Role",
            is_active=False,
        )
        permissions = get_permission_map(["users.view", "roles.view"])
        cls.users_view = permissions["users.view"]
        cls.roles_view = permissions["roles.view"]

    def create_user(self, email, *, is_company_admin=False):
        return UserAccount.objects.create(
            company=self.company,
            first_name="Tenant",
            last_name="User",
            email=email,
            password=make_password("secret123"),
            is_company_admin=is_company_admin,
            is_active=True,
        )

    def auth_headers(self, user):
        token, _ = create_access_token(user)
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_single_role_permission_allows_access(self):
        user = self.create_user("single@example.com")
        UserRole.objects.create(user=user, role=self.primary_role)
        RolePermission.objects.create(role=self.primary_role, permission=self.users_view)

        response = self.client.get("/test/protected/users/", **self.auth_headers(user))

        self.assertEqual(response.status_code, 200)

    def test_multiple_roles_grant_permission_through_second_role(self):
        user = self.create_user("multi@example.com")
        UserRole.objects.create(user=user, role=self.primary_role)
        UserRole.objects.create(user=user, role=self.secondary_role)
        RolePermission.objects.create(role=self.secondary_role, permission=self.users_view)

        response = self.client.get("/test/protected/users/", **self.auth_headers(user))
        auth_echo = self.client.get("/test/auth-echo/", **self.auth_headers(user))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(auth_echo.status_code, 200)
        self.assertCountEqual(
            auth_echo.json()["assigned_role_ids"],
            [str(self.primary_role.id), str(self.secondary_role.id)],
        )

    def test_permission_denied_when_no_assigned_role_grants_it(self):
        user = self.create_user("denied@example.com")
        UserRole.objects.create(user=user, role=self.primary_role)

        response = self.client.get("/test/protected/users/", **self.auth_headers(user))

        self.assertEqual(response.status_code, 403)

    def test_inactive_roles_are_ignored(self):
        user = self.create_user("inactive@example.com")
        UserRole.objects.create(user=user, role=self.inactive_role)
        RolePermission.objects.create(role=self.inactive_role, permission=self.users_view)

        response = self.client.get("/test/protected/users/", **self.auth_headers(user))
        auth_echo = self.client.get("/test/auth-echo/", **self.auth_headers(user))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(auth_echo.status_code, 200)
        self.assertEqual(auth_echo.json()["assigned_role_ids"], [])

    def test_jwt_authentication_payload_is_limited_to_user_and_company(self):
        user = self.create_user("jwt@example.com")
        UserRole.objects.create(user=user, role=self.secondary_role)
        RolePermission.objects.create(role=self.secondary_role, permission=self.users_view)

        token, _ = create_access_token(user)
        payload = decode_access_token(token)

        self.assertEqual(set(payload.keys()), {"user_id", "company_id", "exp"})

    def test_company_admin_still_has_access_without_role_permission(self):
        user = self.create_user("admin@example.com", is_company_admin=True)

        response = self.client.get("/test/protected/admin/", **self.auth_headers(user))
        auth_echo = self.client.get("/test/auth-echo/", **self.auth_headers(user))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(auth_echo.json()["is_company_admin"])


@override_settings(ROOT_URLCONF="accounts.tests")
class PlatformAdminCompatibilityTests(TestCase):
    def test_platform_admin_session_authentication_is_unchanged(self):
        admin_user = get_user_model().objects.create_user(
            username="platform-admin",
            password="secret123",
            is_staff=True,
        )

        response = self.client.post(
            "/platform/login/",
            {"username": admin_user.username, "password": "secret123"},
        )
        dashboard = self.client.get("/platform/dashboard/")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/platform/dashboard/")
        self.assertEqual(dashboard.status_code, 200)

    def test_company_admin_creation_creates_user_role_assignment(self):
        admin_user = get_user_model().objects.create_user(
            username="platform-admin-creator",
            password="secret123",
            is_staff=True,
        )
        company = Company.objects.create(
            legal_name="Provisioned Co",
            tenant_code="provisioned-co",
        )

        self.client.force_login(admin_user)
        response = self.client.post(
            f"/platform/companies/{company.id}/admins/create/",
            {
                "employee_code": "ADMIN-001",
                "first_name": "First",
                "last_name": "Admin",
                "email": "admin@provisioned.example",
                "phone": "1234567890",
                "password": "ProvisionedSecret123!",
            },
        )

        self.assertEqual(response.status_code, 302)
        user = UserAccount.objects.get(company=company, email="admin@provisioned.example")
        self.assertTrue(user.is_company_admin)
        self.assertTrue(
            UserRole.objects.filter(
                user=user,
                role__company=company,
                role__name="Company Admin",
            ).exists()
        )


class TenantUserManagementWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            legal_name="Workflow Co",
            tenant_code="workflow-co",
        )
        cls.other_company = Company.objects.create(
            legal_name="Other Workflow Co",
            tenant_code="other-workflow-co",
        )

        permissions = get_permission_map(
            [
                "users.view",
                "users.create",
                "users.edit",
                "users.update",
                "facilities.view",
            ]
        )
        cls.users_view = permissions["users.view"]
        cls.users_create = permissions["users.create"]
        cls.users_edit = permissions["users.edit"]
        cls.users_update = permissions["users.update"]
        cls.facilities_view = permissions["facilities.view"]

        cls.manager_role = Role.objects.create(company=cls.company, name="User Manager")
        cls.unrestricted_role = Role.objects.create(company=cls.company, name="Unrestricted Operator")
        cls.scoped_role = Role.objects.create(company=cls.company, name="Scoped Operator")
        cls.second_role = Role.objects.create(company=cls.company, name="Second Operator")
        cls.other_company_role = Role.objects.create(company=cls.other_company, name="Foreign Role")

        for permission in (
            cls.users_view,
            cls.users_create,
            cls.users_edit,
            cls.users_update,
        ):
            RolePermission.objects.create(role=cls.manager_role, permission=permission)
        for permission in (cls.facilities_view,):
            RolePermission.objects.create(role=cls.unrestricted_role, permission=permission)
            RolePermission.objects.create(role=cls.scoped_role, permission=permission)
            RolePermission.objects.create(role=cls.second_role, permission=permission)

        cls.department = Department.objects.create(company=cls.company, name="Operations")
        cls.unit_a = OrganizationUnit.objects.create(company=cls.company, name="Unit A")
        cls.unit_b = OrganizationUnit.objects.create(company=cls.company, name="Unit B")
        cls.other_unit = OrganizationUnit.objects.create(company=cls.other_company, name="Other Unit")
        cls.facility_a1 = Facility.objects.create(
            company=cls.company,
            organization_unit=cls.unit_a,
            name="Facility A1",
        )
        cls.facility_a2 = Facility.objects.create(
            company=cls.company,
            organization_unit=cls.unit_b,
            name="Facility A2",
        )
        cls.other_facility = Facility.objects.create(
            company=cls.other_company,
            organization_unit=cls.other_unit,
            name="Other Facility",
        )

        cls.manager_user = UserAccount.objects.create(
            company=cls.company,
            first_name="Manager",
            last_name="User",
            email="manager@example.com",
            password=make_password("secret123"),
            is_active=True,
        )
        UserRole.objects.create(user=cls.manager_user, role=cls.manager_role)

    def auth_headers(self, user):
        token, _ = create_access_token(user)
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def create_company_user(self, email, *, is_company_admin=False):
        return UserAccount.objects.create(
            company=self.company,
            first_name="Existing",
            last_name="User",
            email=email,
            password=make_password("secret123"),
            is_active=True,
            is_company_admin=is_company_admin,
        )

    def assign_role(self, user, role, *, scopes=None):
        assignment = UserRole.objects.create(user=user, role=role)
        for scope_type, scope_ids in (scopes or {}).items():
            for scope_id in scope_ids:
                UserRoleScope.objects.create(
                    user_role=assignment,
                    scope_type=scope_type,
                    scope_id=scope_id,
                )
        return assignment

    def create_payload(self, *, email, roles, first_name="Taylor", last_name="User"):
        return {
            "employee_code": "EMP-001",
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone": "1234567890",
            "password": "TenantSecret123!",
            "department": str(self.department.id),
            "is_active": "on",
            "roles": [str(role.id) for role in roles],
        }

    def update_payload(self, user, *, roles):
        return {
            "employee_code": user.employee_code or "EMP-001",
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "phone": user.phone or "1234567890",
            "department": str(self.department.id),
            "is_active": "on" if user.is_active else "",
            "roles": [str(role.id) for role in roles],
        }

    def add_org_unit_scopes(self, payload, role, *units):
        payload[f"role_scopes__{role.id}__org_unit"] = [str(unit.id) for unit in units]
        return payload

    def add_facility_scopes(self, payload, role, *facilities):
        payload[f"role_scopes__{role.id}__facility"] = [str(facility.id) for facility in facilities]
        return payload

    def test_creating_user_with_one_unrestricted_role(self):
        payload = self.create_payload(
            email="one-role@example.com",
            roles=[self.unrestricted_role],
        )

        response = self.client.post(
            "/accounts/users/create/",
            payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(response.status_code, 302)
        user = UserAccount.objects.get(email="one-role@example.com")
        self.assertEqual(UserRole.objects.filter(user=user).count(), 1)
        self.assertFalse(UserRoleScope.objects.filter(user_role__user=user).exists())

    def test_creating_user_with_multiple_roles(self):
        payload = self.create_payload(
            email="multi-role@example.com",
            roles=[self.unrestricted_role, self.second_role],
        )

        response = self.client.post(
            "/accounts/users/create/",
            payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(response.status_code, 302)
        user = UserAccount.objects.get(email="multi-role@example.com")
        self.assertCountEqual(
            UserRole.objects.filter(user=user).values_list("role_id", flat=True),
            [self.unrestricted_role.id, self.second_role.id],
        )

    def test_assigning_multiple_org_unit_scopes_to_one_role(self):
        payload = self.create_payload(
            email="org-multi@example.com",
            roles=[self.scoped_role],
        )
        self.add_org_unit_scopes(payload, self.scoped_role, self.unit_a, self.unit_b)

        response = self.client.post(
            "/accounts/users/create/",
            payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(response.status_code, 302)
        user = UserAccount.objects.get(email="org-multi@example.com")
        assignment = UserRole.objects.get(user=user, role=self.scoped_role)
        self.assertCountEqual(
            assignment.scopes.values_list("scope_type", "scope_id"),
            [
                ("ORG_UNIT", self.unit_a.id),
                ("ORG_UNIT", self.unit_b.id),
            ],
        )

    def test_assigning_combined_org_unit_and_facility_scopes(self):
        payload = self.create_payload(
            email="combined@example.com",
            roles=[self.scoped_role],
        )
        self.add_org_unit_scopes(payload, self.scoped_role, self.unit_a)
        self.add_facility_scopes(payload, self.scoped_role, self.facility_a1)

        response = self.client.post(
            "/accounts/users/create/",
            payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(response.status_code, 302)
        user = UserAccount.objects.get(email="combined@example.com")
        assignment = UserRole.objects.get(user=user, role=self.scoped_role)
        self.assertCountEqual(
            assignment.scopes.values_list("scope_type", "scope_id"),
            [
                ("ORG_UNIT", self.unit_a.id),
                ("FACILITY", self.facility_a1.id),
            ],
        )

    def test_editing_role_assignments_and_scopes(self):
        user = self.create_company_user("edit-user@example.com")
        self.assign_role(user, self.unrestricted_role)

        payload = self.update_payload(user, roles=[self.scoped_role, self.second_role])
        self.add_org_unit_scopes(payload, self.scoped_role, self.unit_b)
        self.add_facility_scopes(payload, self.scoped_role, self.facility_a2)

        response = self.client.post(
            f"/accounts/users/{user.id}/edit/",
            payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(response.status_code, 302)
        self.assertCountEqual(
            UserRole.objects.filter(user=user).values_list("role_id", flat=True),
            [self.scoped_role.id, self.second_role.id],
        )

    def test_removing_a_role_and_its_scopes(self):
        user = self.create_company_user("remove-role@example.com")
        removed_assignment = self.assign_role(
            user,
            self.scoped_role,
            scopes={
                "ORG_UNIT": [self.unit_a.id],
                "FACILITY": [self.facility_a1.id],
            },
        )
        self.assign_role(user, self.second_role)

        payload = self.update_payload(user, roles=[self.second_role])

        response = self.client.post(
            f"/accounts/users/{user.id}/edit/",
            payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(UserRole.objects.filter(id=removed_assignment.id).exists())
        self.assertFalse(UserRoleScope.objects.filter(user_role=removed_assignment).exists())

    def test_cross_tenant_role_rejection(self):
        payload = self.create_payload(
            email="foreign-role@example.com",
            roles=[self.other_company_role],
        )

        response = self.client.post(
            "/accounts/users/create/",
            payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")

    def test_cross_tenant_scope_target_rejection(self):
        payload = self.create_payload(
            email="foreign-scope@example.com",
            roles=[self.scoped_role],
        )
        payload[f"role_scopes__{self.scoped_role.id}__org_unit"] = [str(self.other_unit.id)]
        payload[f"role_scopes__{self.scoped_role.id}__facility"] = [str(self.other_facility.id)]

        response = self.client.post(
            "/accounts/users/create/",
            payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")

    def test_runtime_authorization_reflects_changes_made_through_ui(self):
        payload = self.create_payload(
            email="runtime-ui@example.com",
            roles=[self.scoped_role],
        )
        self.add_org_unit_scopes(payload, self.scoped_role, self.unit_a)
        self.add_facility_scopes(payload, self.scoped_role, self.facility_a1)

        create_response = self.client.post(
            "/accounts/users/create/",
            payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(create_response.status_code, 302)
        user = UserAccount.objects.get(email="runtime-ui@example.com")
        self.assertTrue(
            authorize(
                user,
                self.facilities_view.code,
                ResourceContext.from_mapping(
                    {
                        "org_unit": [self.unit_a.id],
                        "facility": [self.facility_a1.id],
                    }
                ),
            )
        )

        update_payload = self.update_payload(user, roles=[self.second_role])
        edit_response = self.client.post(
            f"/accounts/users/{user.id}/edit/",
            update_payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(edit_response.status_code, 302)
        self.assertTrue(authorize(user, self.facilities_view.code))

    def test_company_admin_access_remaining_unchanged(self):
        company_admin = self.create_company_user(
            "company-admin@example.com",
            is_company_admin=True,
        )

        response = self.client.get(
            "/accounts/users/",
            **self.auth_headers(company_admin),
        )

        self.assertEqual(response.status_code, 200)

    def test_duplicate_role_assignments_are_rejected(self):
        payload = self.create_payload(
            email="duplicate-role@example.com",
            roles=[self.unrestricted_role, self.unrestricted_role],
        )

        response = self.client.post(
            "/accounts/users/create/",
            payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Duplicate role assignments are not allowed.")

    def test_duplicate_scope_rows_are_rejected(self):
        payload = self.create_payload(
            email="duplicate-scope@example.com",
            roles=[self.scoped_role],
        )
        payload[f"role_scopes__{self.scoped_role.id}__org_unit"] = [
            str(self.unit_a.id),
            str(self.unit_a.id),
        ]

        response = self.client.post(
            "/accounts/users/create/",
            payload,
            **self.auth_headers(self.manager_user),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Duplicate organization unit scope values are not allowed.",
        )

    def test_middleware_restores_assignments_server_side(self):
        user = self.create_company_user("middleware@example.com")
        self.assign_role(user, self.unrestricted_role)
        self.assign_role(user, self.second_role)

        response = self.client.get(
            "/auth/me/",
            **self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(
            [role["id"] for role in response.json()["user"]["roles"]],
            [str(self.unrestricted_role.id), str(self.second_role.id)],
        )

    def test_get_active_user_role_assignments_returns_only_active_same_company_roles(self):
        user = self.create_company_user("active-assignments@example.com")
        active_assignment = self.assign_role(user, self.unrestricted_role)
        inactive_role = Role.objects.create(
            company=self.company,
            name="Inactive Local Role",
            is_active=False,
        )
        self.assign_role(user, inactive_role)

        assignments = list(get_active_user_role_assignments(user))

        self.assertEqual(assignments, [active_assignment])
