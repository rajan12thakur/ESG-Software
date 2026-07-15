from io import StringIO

from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.test import TestCase

from accounts.models import Permission, Role, RolePermission, UserAccount, UserDepartment, UserRole, UserRoleScope
from accounts.permission_catalog import CANONICAL_PERMISSION_CODES, get_permission_map
from accounts.rbac import SCOPE_TYPE_FACILITY, SCOPE_TYPE_ORG_UNIT
from authentication.tokens import create_access_token
from core.models import Company, CompanyProfile, Department, Facility, OrganizationUnit


class OrganizationAreaScopeIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.company = Company.objects.create(
            legal_name="Tenant One",
            tenant_code="tenant-one",
        )
        cls.other_company = Company.objects.create(
            legal_name="Tenant Two",
            tenant_code="tenant-two",
        )

        permissions = get_permission_map(
            [
                "departments.view",
                "departments.create",
                "departments.edit",
                "organization_units.view",
                "organization_units.create",
                "organization_units.edit",
                "facilities.view",
                "facilities.create",
                "facilities.edit",
            ]
        )
        cls.department_view = permissions["departments.view"]
        cls.department_create = permissions["departments.create"]
        cls.department_edit = permissions["departments.edit"]
        cls.org_unit_view = permissions["organization_units.view"]
        cls.org_unit_create = permissions["organization_units.create"]
        cls.org_unit_edit = permissions["organization_units.edit"]
        cls.facility_view = permissions["facilities.view"]
        cls.facility_create = permissions["facilities.create"]
        cls.facility_edit = permissions["facilities.edit"]

        cls.department_role = Role.objects.create(company=cls.company, name="Department Manager")
        cls.org_unit_role = Role.objects.create(company=cls.company, name="Org Unit Manager")
        cls.facility_role = Role.objects.create(company=cls.company, name="Facility Manager")
        cls.admin_role = Role.objects.create(company=cls.company, name="Company Admin")

        for permission in (cls.department_view, cls.department_create, cls.department_edit):
            RolePermission.objects.create(role=cls.department_role, permission=permission)
        for permission in (cls.org_unit_view, cls.org_unit_create, cls.org_unit_edit):
            RolePermission.objects.create(role=cls.org_unit_role, permission=permission)
        for permission in (cls.facility_view, cls.facility_create, cls.facility_edit):
            RolePermission.objects.create(role=cls.facility_role, permission=permission)

        cls.unit_a = OrganizationUnit.objects.create(company=cls.company, name="Unit A")
        cls.unit_b = OrganizationUnit.objects.create(company=cls.company, name="Unit B", parent_unit=cls.unit_a)
        cls.other_unit = OrganizationUnit.objects.create(company=cls.other_company, name="Other Unit")

        cls.facility_a1 = Facility.objects.create(
            company=cls.company,
            organization_unit=cls.unit_a,
            name="Facility A1",
        )
        cls.facility_a2 = Facility.objects.create(
            company=cls.company,
            organization_unit=cls.unit_a,
            name="Facility A2",
        )
        cls.facility_b1 = Facility.objects.create(
            company=cls.company,
            organization_unit=cls.unit_b,
            name="Facility B1",
        )
        cls.other_facility = Facility.objects.create(
            company=cls.other_company,
            organization_unit=cls.other_unit,
            name="Other Facility",
        )

    def create_user(self, email, *, company=None, is_company_admin=False):
        return UserAccount.objects.create(
            company=company or self.company,
            first_name="Scoped",
            last_name="User",
            email=email,
            password=make_password("secret123"),
            is_company_admin=is_company_admin,
            is_active=True,
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

    def auth_headers(self, user):
        token, _ = create_access_token(user)
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_department_creation_derives_authenticated_company(self):
        user = self.create_user("dept-create@example.com")
        self.assign_role(user, self.department_role)

        response = self.client.post(
            "/core/departments/create/",
            {"name": "Derived Department", "description": "Scoped", "is_active": "on"},
            **self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 302)
        department = Department.objects.get(name="Derived Department")
        self.assertEqual(department.company, self.company)

    def test_organization_unit_creation_derives_authenticated_company(self):
        user = self.create_user("unit-create@example.com")
        self.assign_role(user, self.org_unit_role)

        response = self.client.post(
            "/core/organization-units/create/",
            {"name": "Derived Unit", "parent_unit": "", "is_active": "on"},
            **self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 302)
        unit = OrganizationUnit.objects.get(name="Derived Unit")
        self.assertEqual(unit.company, self.company)

    def test_unrestricted_user_sees_all_permitted_organization_units_and_facilities(self):
        user = self.create_user("unrestricted@example.com")
        self.assign_role(user, self.org_unit_role)
        self.assign_role(user, self.facility_role)

        unit_response = self.client.get("/core/organization-units/", **self.auth_headers(user))
        facility_response = self.client.get(
            f"/core/organization-units/{self.unit_a.id}/facilities/",
            **self.auth_headers(user),
        )

        self.assertCountEqual(
            [item.id for item in unit_response.context["items"]],
            [self.unit_a.id, self.unit_b.id],
        )
        self.assertCountEqual(
            [item.id for item in facility_response.context["facilities"]],
            [self.facility_a1.id, self.facility_a2.id],
        )

    def test_org_unit_scoped_user_sees_only_allowed_organization_units(self):
        user = self.create_user("org-scoped@example.com")
        self.assign_role(
            user,
            self.org_unit_role,
            scopes={SCOPE_TYPE_ORG_UNIT: [self.unit_a.id]},
        )

        response = self.client.get("/core/organization-units/", **self.auth_headers(user))

        self.assertEqual([item.id for item in response.context["items"]], [self.unit_a.id])

    def test_facility_scoped_user_sees_only_allowed_facilities(self):
        user = self.create_user("facility-scoped@example.com")
        self.assign_role(
            user,
            self.facility_role,
            scopes={SCOPE_TYPE_FACILITY: [self.facility_a1.id]},
        )

        response = self.client.get(
            f"/core/organization-units/{self.unit_a.id}/facilities/",
            **self.auth_headers(user),
        )

        self.assertEqual([item.id for item in response.context["facilities"]], [self.facility_a1.id])

    def test_facility_access_respects_both_facility_and_org_unit_scope_groups(self):
        user = self.create_user("facility-and-org@example.com")
        self.assign_role(
            user,
            self.facility_role,
            scopes={
                SCOPE_TYPE_FACILITY: [self.facility_a1.id],
                SCOPE_TYPE_ORG_UNIT: [self.unit_b.id],
            },
        )

        response = self.client.get(
            f"/core/organization-units/{self.unit_a.id}/facilities/",
            **self.auth_headers(user),
        )
        edit_response = self.client.get(
            f"/core/organization-units/{self.unit_a.id}/facilities/{self.facility_a1.id}/edit/",
            **self.auth_headers(user),
        )

        self.assertEqual(list(response.context["facilities"]), [])
        self.assertEqual(edit_response.status_code, 403)

    def test_scoped_user_cannot_edit_unauthorized_object_by_direct_url(self):
        user = self.create_user("direct-url@example.com")
        self.assign_role(
            user,
            self.org_unit_role,
            scopes={SCOPE_TYPE_ORG_UNIT: [self.unit_a.id]},
        )

        response = self.client.get(
            f"/core/organization-units/{self.unit_b.id}/edit/",
            **self.auth_headers(user),
        )

        self.assertEqual(response.status_code, 403)

    def test_cross_tenant_access_is_rejected(self):
        user = self.create_user("cross-tenant@example.com")
        self.assign_role(user, self.org_unit_role)
        self.assign_role(user, self.facility_role)
        self.assign_role(user, self.department_role)

        unit_response = self.client.get(
            f"/core/organization-units/{self.other_unit.id}/edit/",
            **self.auth_headers(user),
        )
        facility_response = self.client.get(
            f"/core/organization-units/{self.other_unit.id}/facilities/{self.other_facility.id}/edit/",
            **self.auth_headers(user),
        )

        self.assertEqual(unit_response.status_code, 404)
        self.assertEqual(facility_response.status_code, 404)

    def test_multiple_roles_remain_additive(self):
        user = self.create_user("additive@example.com")
        self.assign_role(
            user,
            self.org_unit_role,
            scopes={SCOPE_TYPE_ORG_UNIT: [self.unit_a.id]},
        )
        second_role = Role.objects.create(company=self.company, name="Secondary Org Viewer")
        RolePermission.objects.create(role=second_role, permission=self.org_unit_view)
        self.assign_role(
            user,
            second_role,
            scopes={SCOPE_TYPE_ORG_UNIT: [self.unit_b.id]},
        )

        response = self.client.get("/core/organization-units/", **self.auth_headers(user))

        self.assertCountEqual(
            [item.id for item in response.context["items"]],
            [self.unit_a.id, self.unit_b.id],
        )

    def test_company_admin_bypass_remains_functional(self):
        user = self.create_user(
            "company-admin@example.com",
            is_company_admin=True,
        )

        list_response = self.client.get("/core/organization-units/", **self.auth_headers(user))
        create_response = self.client.post(
            "/core/departments/create/",
            {"name": "Admin Department", "description": "Bypass", "is_active": "on"},
            **self.auth_headers(user),
        )

        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(create_response.status_code, 302)
        self.assertTrue(
            Department.objects.filter(company=self.company, name="Admin Department").exists()
        )


class Module1DevelopmentSeedCommandTests(TestCase):
    command_name = "seed_module1_demo"
    password = "SeedTest123!"

    def run_seed(self, *extra_args, **extra_options):
        stdout = StringIO()
        call_command(
            self.command_name,
            *extra_args,
            password=self.password,
            stdout=stdout,
            **extra_options,
        )
        return stdout.getvalue()

    def test_successful_seed_execution(self):
        output = self.run_seed()

        self.assertIn("Aurelia Precision Components", output)
        self.assertIn("tenant_code=aurelia-precision", output)
        self.assertIn("rohan.kulkarni@aurelia-demo.invalid", output)
        self.assertNotIn(self.password, output)
        self.assertEqual(
            Company.objects.filter(
                registration_number__in=["SEED-MODULE1-AURELIA", "SEED-MODULE1-NEXORA"],
                is_demo_tenant=True,
            ).count(),
            2,
        )
        self.assertEqual(
            Company.objects.filter(
                tenant_code__in=["aurelia-precision", "nexora-logistics"],
            ).count(),
            2,
        )
        self.assertEqual(CompanyProfile.objects.count(), 2)
        self.assertEqual(
            UserAccount.objects.filter(email__regex=r"@(aurelia|nexora)-demo\.invalid$").count(),
            8,
        )

    def test_repeated_execution_is_idempotent(self):
        self.run_seed()
        first_counts = {
            "permissions": Permission.objects.count(),
            "companies": Company.objects.count(),
            "profiles": CompanyProfile.objects.count(),
            "departments": Department.objects.count(),
            "org_units": OrganizationUnit.objects.count(),
            "facilities": Facility.objects.count(),
            "roles": Role.objects.count(),
            "role_permissions": RolePermission.objects.count(),
            "users": UserAccount.objects.count(),
            "user_roles": UserRole.objects.count(),
            "user_role_scopes": UserRoleScope.objects.count(),
            "user_departments": UserDepartment.objects.count(),
        }

        self.run_seed()
        second_counts = {
            "permissions": Permission.objects.count(),
            "companies": Company.objects.count(),
            "profiles": CompanyProfile.objects.count(),
            "departments": Department.objects.count(),
            "org_units": OrganizationUnit.objects.count(),
            "facilities": Facility.objects.count(),
            "roles": Role.objects.count(),
            "role_permissions": RolePermission.objects.count(),
            "users": UserAccount.objects.count(),
            "user_roles": UserRole.objects.count(),
            "user_role_scopes": UserRoleScope.objects.count(),
            "user_departments": UserDepartment.objects.count(),
        }

        self.assertEqual(first_counts, second_counts)

    def test_seed_command_uses_canonical_permission_catalog(self):
        self.run_seed()

        self.assertEqual(Permission.objects.count(), len(CANONICAL_PERMISSION_CODES))
        self.assertCountEqual(
            Permission.objects.values_list("code", flat=True),
            CANONICAL_PERMISSION_CODES,
        )

    def test_correct_user_role_assignments_are_seeded(self):
        self.run_seed()
        additive_user = UserAccount.objects.get(email="kavya.iyer@aurelia-demo.invalid")
        combined_user = UserAccount.objects.get(email="arjun.rao@aurelia-demo.invalid")

        self.assertCountEqual(
            additive_user.user_roles.select_related("role").values_list("role__name", flat=True),
            [
                "Manufacturing Division Viewer",
                "Distribution Division Viewer",
            ],
        )
        self.assertCountEqual(
            combined_user.user_roles.select_related("role").values_list("role__name", flat=True),
            ["Plant Compliance Coordinator"],
        )

    def test_correct_user_role_scope_assignments_are_seeded(self):
        self.run_seed()
        manufacturing_unit = OrganizationUnit.objects.get(name="Western Manufacturing Division")
        logistics_unit = OrganizationUnit.objects.get(name="Supply Chain and Distribution Division")
        facility = Facility.objects.get(name="Chakan Components Plant")

        additive_user = UserAccount.objects.get(email="kavya.iyer@aurelia-demo.invalid")
        combined_user = UserAccount.objects.get(email="arjun.rao@aurelia-demo.invalid")

        self.assertCountEqual(
            additive_user.user_roles.get(role__name="Manufacturing Division Viewer")
            .scopes.values_list("scope_type", "scope_id"),
            [(SCOPE_TYPE_ORG_UNIT, manufacturing_unit.id)],
        )
        self.assertCountEqual(
            additive_user.user_roles.get(role__name="Distribution Division Viewer")
            .scopes.values_list("scope_type", "scope_id"),
            [(SCOPE_TYPE_ORG_UNIT, logistics_unit.id)],
        )
        self.assertCountEqual(
            combined_user.user_roles.get(role__name="Plant Compliance Coordinator")
            .scopes.values_list("scope_type", "scope_id"),
            [
                (SCOPE_TYPE_ORG_UNIT, manufacturing_unit.id),
                (SCOPE_TYPE_FACILITY, facility.id),
            ],
        )

    def test_seeded_data_remains_separated_by_company(self):
        self.run_seed()
        alpha_company = Company.objects.get(tenant_code="aurelia-precision")
        beta_company = Company.objects.get(tenant_code="nexora-logistics")

        self.assertTrue(
            OrganizationUnit.objects.filter(company=alpha_company, name="Western Manufacturing Division").exists()
        )
        self.assertFalse(
            OrganizationUnit.objects.filter(company=beta_company, name="Western Manufacturing Division").exists()
        )
        self.assertTrue(
            Facility.objects.filter(company=beta_company, name="Chennai Freight Terminal").exists()
        )
        self.assertFalse(
            Facility.objects.filter(company=alpha_company, name="Chennai Freight Terminal").exists()
        )

    def test_seeded_users_can_share_email_across_different_companies_if_needed(self):
        self.run_seed()
        shared_email = "shared@module1-demo.invalid"
        alpha = Company.objects.get(tenant_code="aurelia-precision")
        beta = Company.objects.get(tenant_code="nexora-logistics")

        UserAccount.objects.create(
            company=alpha,
            first_name="Shared",
            last_name="Alpha",
            email=shared_email,
            password=make_password("Secret123!"),
        )
        UserAccount.objects.create(
            company=beta,
            first_name="Shared",
            last_name="Beta",
            email=shared_email,
            password=make_password("Secret123!"),
        )

        self.assertEqual(UserAccount.objects.filter(email=shared_email).count(), 2)
