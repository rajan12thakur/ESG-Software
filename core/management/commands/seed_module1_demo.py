import os
from collections import defaultdict

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Role, RolePermission, UserAccount, UserDepartment, UserRole, UserRoleScope
from accounts.permission_catalog import (
    CANONICAL_PERMISSION_CODES,
    get_permission_map,
    sync_permission_catalog,
)
from accounts.rbac import SCOPE_TYPE_FACILITY, SCOPE_TYPE_ORG_UNIT
from core.models import Company, CompanyProfile, Department, Facility, OrganizationUnit

PASSWORD_ENV_VAR = "MODULE1_DEMO_PASSWORD"
SEED_REGISTRATION_NUMBERS = {
    "alpha": "SEED-MODULE1-ALPHA",
    "beta": "SEED-MODULE1-BETA",
}

COMPANY_SPECS = {
    "alpha": {
        "company": {
            "legal_name": "Module 1 Demo Alpha LLC",
            "display_name": "Module 1 Demo Alpha",
            "tenant_code": "module1-alpha",
            "registration_number": SEED_REGISTRATION_NUMBERS["alpha"],
            "industry": "Manufacturing",
            "country": "United States",
            "currency": "USD",
            "timezone": "America/New_York",
            "status": "active",
            "is_demo_tenant": True,
        },
        "profile": {
            "sector": "Industrials",
            "sub_sector": "Manufacturing",
            "employee_count": 1200,
            "annual_revenue": "85000000.00",
            "listed_status": "Private",
            "stock_exchange": "",
            "description": "Development seed tenant for current Module 1 RBAC and scope testing.",
        },
        "departments": [
            ("Operations", "Operational delivery and execution."),
            ("Sustainability", "ESG program ownership."),
        ],
        "organization_units": [
            {
                "name": "Alpha Group",
                "parent": None,
                "unit_type": "Holding",
                "country": "United States",
                "state": "New York",
                "city": "New York",
            },
            {
                "name": "Alpha Manufacturing",
                "parent": "Alpha Group",
                "unit_type": "Plant Division",
                "country": "United States",
                "state": "Ohio",
                "city": "Cleveland",
            },
            {
                "name": "Alpha Logistics",
                "parent": "Alpha Group",
                "unit_type": "Distribution",
                "country": "United States",
                "state": "Illinois",
                "city": "Chicago",
            },
        ],
        "facilities": [
            {
                "name": "Alpha Plant 1",
                "organization_unit": "Alpha Manufacturing",
                "facility_type": "Plant",
                "country": "United States",
                "state": "Ohio",
                "city": "Cleveland",
            },
            {
                "name": "Alpha Plant 2",
                "organization_unit": "Alpha Manufacturing",
                "facility_type": "Plant",
                "country": "United States",
                "state": "Ohio",
                "city": "Toledo",
            },
            {
                "name": "Alpha Logistics Hub",
                "organization_unit": "Alpha Logistics",
                "facility_type": "Warehouse",
                "country": "United States",
                "state": "Illinois",
                "city": "Chicago",
            },
        ],
        "roles": {
            "Company Admin": {
                "description": "Module 1 demo company administrator.",
                "is_system_role": True,
                "permissions": list(CANONICAL_PERMISSION_CODES),
            },
            "Module 1 Unrestricted Operator": {
                "description": "Unrestricted tenant operator for organization-area testing.",
                "permissions": [
                    "departments.view",
                    "departments.create",
                    "departments.edit",
                    "organization_units.view",
                    "organization_units.create",
                    "organization_units.edit",
                    "facilities.view",
                    "facilities.create",
                    "facilities.edit",
                ],
            },
            "Module 1 Additive Manufacturing": {
                "description": "Additive scope role for Alpha Manufacturing.",
                "permissions": ["organization_units.view"],
            },
            "Module 1 Additive Logistics": {
                "description": "Additive scope role for Alpha Logistics.",
                "permissions": ["organization_units.view"],
            },
            "Module 1 ORG_UNIT Scoped": {
                "description": "Scoped to one organization unit.",
                "permissions": [
                    "organization_units.view",
                    "organization_units.create",
                    "organization_units.edit",
                ],
            },
            "Module 1 FACILITY Scoped": {
                "description": "Scoped to one facility.",
                "permissions": [
                    "facilities.view",
                    "facilities.create",
                    "facilities.edit",
                ],
            },
            "Module 1 Combined Scoped": {
                "description": "Requires both matching organization unit and facility scopes.",
                "permissions": [
                    "facilities.view",
                    "facilities.edit",
                ],
            },
        },
        "users": [
            {
                "email": "alpha.admin@module1-demo.invalid",
                "employee_code": "M1DEMO-ALPHA-ADMIN",
                "first_name": "Alpha",
                "last_name": "Admin",
                "phone": "+1-555-0100",
                "department": "Operations",
                "is_company_admin": True,
                "roles": [{"name": "Company Admin"}],
            },
            {
                "email": "alpha.unrestricted@module1-demo.invalid",
                "employee_code": "M1DEMO-ALPHA-UNRESTRICTED",
                "first_name": "Alpha",
                "last_name": "Unrestricted",
                "phone": "+1-555-0101",
                "department": "Operations",
                "roles": [{"name": "Module 1 Unrestricted Operator"}],
            },
            {
                "email": "alpha.additive@module1-demo.invalid",
                "employee_code": "M1DEMO-ALPHA-ADDITIVE",
                "first_name": "Alpha",
                "last_name": "Additive",
                "phone": "+1-555-0102",
                "department": "Sustainability",
                "roles": [
                    {
                        "name": "Module 1 Additive Manufacturing",
                        "scopes": {SCOPE_TYPE_ORG_UNIT: ["Alpha Manufacturing"]},
                    },
                    {
                        "name": "Module 1 Additive Logistics",
                        "scopes": {SCOPE_TYPE_ORG_UNIT: ["Alpha Logistics"]},
                    },
                ],
            },
            {
                "email": "alpha.orgunit@module1-demo.invalid",
                "employee_code": "M1DEMO-ALPHA-ORGUNIT",
                "first_name": "Alpha",
                "last_name": "OrgUnit",
                "phone": "+1-555-0103",
                "department": "Operations",
                "roles": [
                    {
                        "name": "Module 1 ORG_UNIT Scoped",
                        "scopes": {SCOPE_TYPE_ORG_UNIT: ["Alpha Manufacturing"]},
                    }
                ],
            },
            {
                "email": "alpha.facility@module1-demo.invalid",
                "employee_code": "M1DEMO-ALPHA-FACILITY",
                "first_name": "Alpha",
                "last_name": "Facility",
                "phone": "+1-555-0104",
                "department": "Operations",
                "roles": [
                    {
                        "name": "Module 1 FACILITY Scoped",
                        "scopes": {SCOPE_TYPE_FACILITY: ["Alpha Plant 1"]},
                    }
                ],
            },
            {
                "email": "alpha.combined@module1-demo.invalid",
                "employee_code": "M1DEMO-ALPHA-COMBINED",
                "first_name": "Alpha",
                "last_name": "Combined",
                "phone": "+1-555-0105",
                "department": "Operations",
                "roles": [
                    {
                        "name": "Module 1 Combined Scoped",
                        "scopes": {
                            SCOPE_TYPE_ORG_UNIT: ["Alpha Manufacturing"],
                            SCOPE_TYPE_FACILITY: ["Alpha Plant 1"],
                        },
                    }
                ],
            },
        ],
    },
    "beta": {
        "company": {
            "legal_name": "Module 1 Demo Beta LLC",
            "display_name": "Module 1 Demo Beta",
            "tenant_code": "module1-beta",
            "registration_number": SEED_REGISTRATION_NUMBERS["beta"],
            "industry": "Logistics",
            "country": "United States",
            "currency": "USD",
            "timezone": "America/Chicago",
            "status": "active",
            "is_demo_tenant": True,
        },
        "profile": {
            "sector": "Industrials",
            "sub_sector": "Transportation",
            "employee_count": 450,
            "annual_revenue": "22000000.00",
            "listed_status": "Private",
            "stock_exchange": "",
            "description": "Second development seed tenant for tenant-isolation testing.",
        },
        "departments": [
            ("Operations", "Operational execution."),
            ("Compliance", "Regulatory and ESG oversight."),
        ],
        "organization_units": [
            {
                "name": "Beta Holdings",
                "parent": None,
                "unit_type": "Holding",
                "country": "United States",
                "state": "Texas",
                "city": "Dallas",
            },
            {
                "name": "Beta South Region",
                "parent": "Beta Holdings",
                "unit_type": "Regional Operations",
                "country": "United States",
                "state": "Texas",
                "city": "Houston",
            },
        ],
        "facilities": [
            {
                "name": "Beta Terminal 1",
                "organization_unit": "Beta South Region",
                "facility_type": "Terminal",
                "country": "United States",
                "state": "Texas",
                "city": "Houston",
            },
            {
                "name": "Beta Warehouse 1",
                "organization_unit": "Beta South Region",
                "facility_type": "Warehouse",
                "country": "United States",
                "state": "Texas",
                "city": "Austin",
            },
        ],
        "roles": {
            "Company Admin": {
                "description": "Module 1 demo company administrator.",
                "is_system_role": True,
                "permissions": list(CANONICAL_PERMISSION_CODES),
            },
            "Module 1 Beta Unrestricted Operator": {
                "description": "Unrestricted operator for tenant isolation testing.",
                "permissions": [
                    "departments.view",
                    "organization_units.view",
                    "facilities.view",
                ],
            },
        },
        "users": [
            {
                "email": "beta.admin@module1-demo.invalid",
                "employee_code": "M1DEMO-BETA-ADMIN",
                "first_name": "Beta",
                "last_name": "Admin",
                "phone": "+1-555-0200",
                "department": "Operations",
                "is_company_admin": True,
                "roles": [{"name": "Company Admin"}],
            },
            {
                "email": "beta.unrestricted@module1-demo.invalid",
                "employee_code": "M1DEMO-BETA-UNRESTRICTED",
                "first_name": "Beta",
                "last_name": "Operator",
                "phone": "+1-555-0201",
                "department": "Compliance",
                "roles": [{"name": "Module 1 Beta Unrestricted Operator"}],
            },
        ],
    },
}


class Command(BaseCommand):
    help = "Seed two demo tenants and current Module 1 RBAC/scope data for development testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            help=f"Development password for all seeded tenant users. Falls back to {PASSWORD_ENV_VAR}.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete only seed-owned companies and reseed them from scratch.",
        )

    def handle(self, *args, **options):
        password = options.get("password") or os.environ.get(PASSWORD_ENV_VAR)
        if not password:
            raise CommandError(
                f"Provide a development password with --password or the {PASSWORD_ENV_VAR} environment variable."
            )

        with transaction.atomic():
            if options.get("reset"):
                deleted = self.reset_seed_data()
                self.stdout.write(self.style.WARNING(f"Reset seed-owned companies: {deleted} removed."))

            seeded = self.seed_all(password=password)

        self.print_summary(seeded)

    def reset_seed_data(self):
        companies = Company.objects.filter(
            registration_number__in=SEED_REGISTRATION_NUMBERS.values(),
            is_demo_tenant=True,
        )
        count = companies.count()
        companies.delete()
        return count

    def seed_all(self, *, password):
        permissions = self.ensure_permissions()
        seeded = {}

        for key, spec in COMPANY_SPECS.items():
            company = self.ensure_company(spec["company"])
            self.ensure_profile(company, spec["profile"])
            departments = self.ensure_departments(company, spec["departments"])
            org_units = self.ensure_organization_units(company, spec["organization_units"])
            facilities = self.ensure_facilities(company, spec["facilities"], org_units)
            roles = self.ensure_roles(company, spec["roles"], permissions)
            users = self.ensure_users(
                company=company,
                user_specs=spec["users"],
                roles=roles,
                departments=departments,
                org_units=org_units,
                facilities=facilities,
                password=password,
            )
            seeded[key] = {
                "company": company,
                "roles": roles,
                "users": users,
                "departments": departments,
                "org_units": org_units,
                "facilities": facilities,
            }
        return seeded

    def ensure_permissions(self):
        sync_permission_catalog()
        return get_permission_map()

    def ensure_company(self, defaults):
        company, _ = Company.objects.update_or_create(
            tenant_code=defaults["tenant_code"],
            defaults=defaults,
        )
        return company

    def ensure_profile(self, company, defaults):
        CompanyProfile.objects.update_or_create(company=company, defaults=defaults)

    def ensure_departments(self, company, department_specs):
        departments = {}
        for name, description in department_specs:
            department, _ = Department.objects.update_or_create(
                company=company,
                name=name,
                defaults={"description": description, "is_active": True},
            )
            departments[name] = department
        return departments

    def ensure_organization_units(self, company, unit_specs):
        units = {}
        for spec in unit_specs:
            parent = units.get(spec["parent"])
            defaults = {
                "parent_unit": parent,
                "unit_type": spec.get("unit_type", ""),
                "country": spec.get("country", ""),
                "state": spec.get("state", ""),
                "city": spec.get("city", ""),
                "ownership_percentage": spec.get("ownership_percentage"),
                "operational_control": spec.get("operational_control", False),
                "financial_control": spec.get("financial_control", False),
                "is_active": spec.get("is_active", True),
            }
            unit, _ = OrganizationUnit.objects.update_or_create(
                company=company,
                name=spec["name"],
                defaults=defaults,
            )
            units[spec["name"]] = unit
        return units

    def ensure_facilities(self, company, facility_specs, org_units):
        facilities = {}
        for spec in facility_specs:
            unit = org_units[spec["organization_unit"]]
            defaults = {
                "facility_type": spec.get("facility_type", ""),
                "address": spec.get("address", ""),
                "country": spec.get("country", ""),
                "state": spec.get("state", ""),
                "city": spec.get("city", ""),
                "latitude": spec.get("latitude"),
                "longitude": spec.get("longitude"),
                "is_active": spec.get("is_active", True),
            }
            facility, _ = Facility.objects.update_or_create(
                company=company,
                organization_unit=unit,
                name=spec["name"],
                defaults=defaults,
            )
            facilities[spec["name"]] = facility
        return facilities

    def ensure_roles(self, company, role_specs, permissions):
        roles = {}
        for role_name, spec in role_specs.items():
            role, _ = Role.objects.update_or_create(
                company=company,
                name=role_name,
                defaults={
                    "description": spec.get("description", ""),
                    "is_system_role": spec.get("is_system_role", False),
                    "is_active": True,
                },
            )
            for permission_code in spec.get("permissions", ()):
                RolePermission.objects.get_or_create(
                    role=role,
                    permission=permissions[permission_code],
                )
            roles[role_name] = role
        return roles

    def ensure_users(
        self,
        *,
        company,
        user_specs,
        roles,
        departments,
        org_units,
        facilities,
        password,
    ):
        users = {}
        for spec in user_specs:
            user, _ = UserAccount.objects.update_or_create(
                company=company,
                email=spec["email"],
                defaults={
                    "employee_code": spec.get("employee_code", ""),
                    "first_name": spec["first_name"],
                    "last_name": spec.get("last_name", ""),
                    "phone": spec.get("phone", ""),
                    "password": make_password(password),
                    "is_company_admin": spec.get("is_company_admin", False),
                    "is_active": True,
                },
            )

            department = departments.get(spec.get("department"))
            UserDepartment.objects.filter(user=user).delete()
            if department is not None:
                UserDepartment.objects.get_or_create(user=user, department=department)

            role_names = [role_spec["name"] for role_spec in spec["roles"]]
            UserRole.objects.filter(user=user).exclude(
                role__name__in=role_names,
                role__company=company,
            ).delete()

            assignments = []
            for role_spec in spec["roles"]:
                role = roles[role_spec["name"]]
                assignment, _ = UserRole.objects.get_or_create(
                    user=user,
                    role=role,
                    defaults={"assigned_by": None},
                )
                assignment.scopes.all().delete()
                for scope_type, scope_names in role_spec.get("scopes", {}).items():
                    for scope_name in scope_names:
                        scope_id = self.resolve_scope_id(
                            scope_type=scope_type,
                            scope_name=scope_name,
                            org_units=org_units,
                            facilities=facilities,
                        )
                        UserRoleScope.objects.get_or_create(
                            user_role=assignment,
                            scope_type=scope_type,
                            scope_id=scope_id,
                        )
                assignments.append(assignment)
            users[spec["email"]] = {"user": user, "assignments": assignments}
        return users

    def resolve_scope_id(self, *, scope_type, scope_name, org_units, facilities):
        scope_type = scope_type.upper()
        if scope_type == SCOPE_TYPE_ORG_UNIT:
            return org_units[scope_name].id
        if scope_type == SCOPE_TYPE_FACILITY:
            return facilities[scope_name].id
        raise CommandError(f"Unsupported scope type in seed spec: {scope_type}")

    def print_summary(self, seeded):
        self.stdout.write(self.style.SUCCESS("Seeded current Module 1 demo data."))
        for payload in seeded.values():
            company = payload["company"]
            self.stdout.write(f"Company: {company.display_name or company.legal_name} ({company.registration_number})")
            for user_payload in payload["users"].values():
                user = user_payload["user"]
                role_descriptions = []
                for assignment in user_payload["assignments"]:
                    scopes = list(
                        assignment.scopes.order_by("scope_type", "scope_id").values_list(
                            "scope_type",
                            "scope_id",
                        )
                    )
                    if not scopes:
                        role_descriptions.append(f"{assignment.role.name} [unrestricted]")
                        continue
                    grouped = defaultdict(list)
                    for scope_type, scope_id in scopes:
                        grouped[scope_type.upper()].append(self.resolve_scope_label(scope_type, scope_id))
                    scope_summary = "; ".join(
                        f"{scope_type}={', '.join(labels)}"
                        for scope_type, labels in sorted(grouped.items())
                    )
                    role_descriptions.append(f"{assignment.role.name} [{scope_summary}]")
                self.stdout.write(
                    f"  - {user.email} | tenant_code={company.tenant_code} | company={company.display_name or company.legal_name} | roles={'; '.join(role_descriptions)}"
                )

    def resolve_scope_label(self, scope_type, scope_id):
        scope_type = scope_type.upper()
        if scope_type == SCOPE_TYPE_ORG_UNIT:
            return OrganizationUnit.objects.filter(id=scope_id).values_list("name", flat=True).first() or str(scope_id)
        if scope_type == SCOPE_TYPE_FACILITY:
            return Facility.objects.filter(id=scope_id).values_list("name", flat=True).first() or str(scope_id)
        return str(scope_id)
