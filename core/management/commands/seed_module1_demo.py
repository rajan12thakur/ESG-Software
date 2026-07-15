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
    "aurelia": "SEED-MODULE1-AURELIA",
    "nexora": "SEED-MODULE1-NEXORA",
}

COMPANY_SPECS = {
    "aurelia": {
        "company": {
            "legal_name": "Aurelia Precision Components Private Limited",
            "display_name": "Aurelia Precision Components",
            "tenant_code": "aurelia-precision",
            "registration_number": SEED_REGISTRATION_NUMBERS["aurelia"],
            "industry": "Automotive Components Manufacturing",
            "country": "India",
            "currency": "INR",
            "timezone": "Asia/Kolkata",
            "status": "active",
            "is_demo_tenant": True,
        },
        "profile": {
            "sector": "Industrials",
            "sub_sector": "Auto Components",
            "employee_count": 1850,
            "annual_revenue": "6850000000.00",
            "listed_status": "Private",
            "stock_exchange": "",
            "description": "Fictional automotive-components manufacturer used for RBAC, organization hierarchy, and facility-scope testing.",
        },
        "departments": [
            ("Operations", "Production planning, plant operations, quality coordination, and delivery execution."),
            ("Sustainability", "Environmental, social, governance, and sustainability reporting ownership."),
        ],
        "organization_units": [
            {
                "name": "Aurelia Corporate Group",
                "parent": None,
                "unit_type": "Corporate Headquarters",
                "country": "India",
                "state": "Maharashtra",
                "city": "Pune",
            },
            {
                "name": "Western Manufacturing Division",
                "parent": "Aurelia Corporate Group",
                "unit_type": "Manufacturing Division",
                "country": "India",
                "state": "Maharashtra",
                "city": "Pune",
            },
            {
                "name": "Supply Chain and Distribution Division",
                "parent": "Aurelia Corporate Group",
                "unit_type": "Supply Chain Division",
                "country": "India",
                "state": "Maharashtra",
                "city": "Mumbai",
            },
        ],
        "facilities": [
            {
                "name": "Chakan Components Plant",
                "organization_unit": "Western Manufacturing Division",
                "facility_type": "Plant",
                "country": "India",
                "state": "Maharashtra",
                "city": "Pune",
            },
            {
                "name": "Nashik Machining Plant",
                "organization_unit": "Western Manufacturing Division",
                "facility_type": "Plant",
                "country": "India",
                "state": "Maharashtra",
                "city": "Nashik",
            },
            {
                "name": "Bhiwandi Distribution Centre",
                "organization_unit": "Supply Chain and Distribution Division",
                "facility_type": "Distribution Centre",
                "country": "India",
                "state": "Maharashtra",
                "city": "Bhiwandi",
            },
        ],
        "roles": {
            "Company Admin": {
                "description": "Full-access tenant administrator responsible for company configuration and user administration.",
                "is_system_role": True,
                "permissions": list(CANONICAL_PERMISSION_CODES),
            },
            "Operations Platform Manager": {
                "description": "Unrestricted operations manager with department, organization-unit, and facility administration access.",
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
            "Manufacturing Division Viewer": {
                "description": "Read-only organization-unit access for the Western Manufacturing Division.",
                "permissions": ["organization_units.view"],
            },
            "Distribution Division Viewer": {
                "description": "Read-only organization-unit access for the Supply Chain and Distribution Division.",
                "permissions": ["organization_units.view"],
            },
            "Organization Unit Manager": {
                "description": "Create, view, and edit access restricted to an assigned organization unit.",
                "permissions": [
                    "organization_units.view",
                    "organization_units.create",
                    "organization_units.edit",
                ],
            },
            "Facility Operations Manager": {
                "description": "Create, view, and edit access restricted to an assigned facility.",
                "permissions": [
                    "facilities.view",
                    "facilities.create",
                    "facilities.edit",
                ],
            },
            "Plant Compliance Coordinator": {
                "description": "Facility editing access requiring both the assigned manufacturing division and plant scope.",
                "permissions": [
                    "facilities.view",
                    "facilities.edit",
                ],
            },
        },
        "users": [
            {
                "email": "ananya.mehta@aurelia-demo.invalid",
                "employee_code": "APCL-ADM-001",
                "first_name": "Ananya",
                "last_name": "Mehta",
                "phone": "+91-90000-00001",
                "department": "Operations",
                "is_company_admin": True,
                "roles": [{"name": "Company Admin"}],
            },
            {
                "email": "rohan.kulkarni@aurelia-demo.invalid",
                "employee_code": "APCL-OPS-014",
                "first_name": "Rohan",
                "last_name": "Kulkarni",
                "phone": "+91-90000-00002",
                "department": "Operations",
                "roles": [{"name": "Operations Platform Manager"}],
            },
            {
                "email": "kavya.iyer@aurelia-demo.invalid",
                "employee_code": "APCL-ESG-008",
                "first_name": "Kavya",
                "last_name": "Iyer",
                "phone": "+91-90000-00003",
                "department": "Sustainability",
                "roles": [
                    {
                        "name": "Manufacturing Division Viewer",
                        "scopes": {SCOPE_TYPE_ORG_UNIT: ["Western Manufacturing Division"]},
                    },
                    {
                        "name": "Distribution Division Viewer",
                        "scopes": {SCOPE_TYPE_ORG_UNIT: ["Supply Chain and Distribution Division"]},
                    },
                ],
            },
            {
                "email": "vikram.patil@aurelia-demo.invalid",
                "employee_code": "APCL-MFG-021",
                "first_name": "Vikram",
                "last_name": "Patil",
                "phone": "+91-90000-00004",
                "department": "Operations",
                "roles": [
                    {
                        "name": "Organization Unit Manager",
                        "scopes": {SCOPE_TYPE_ORG_UNIT: ["Western Manufacturing Division"]},
                    }
                ],
            },
            {
                "email": "sneha.deshmukh@aurelia-demo.invalid",
                "employee_code": "APCL-PLT-032",
                "first_name": "Sneha",
                "last_name": "Deshmukh",
                "phone": "+91-90000-00005",
                "department": "Operations",
                "roles": [
                    {
                        "name": "Facility Operations Manager",
                        "scopes": {SCOPE_TYPE_FACILITY: ["Chakan Components Plant"]},
                    }
                ],
            },
            {
                "email": "arjun.rao@aurelia-demo.invalid",
                "employee_code": "APCL-CMP-011",
                "first_name": "Arjun",
                "last_name": "Rao",
                "phone": "+91-90000-00006",
                "department": "Operations",
                "roles": [
                    {
                        "name": "Plant Compliance Coordinator",
                        "scopes": {
                            SCOPE_TYPE_ORG_UNIT: ["Western Manufacturing Division"],
                            SCOPE_TYPE_FACILITY: ["Chakan Components Plant"],
                        },
                    }
                ],
            },
        ],
    },
    "nexora": {
        "company": {
            "legal_name": "Nexora Freight and Logistics Private Limited",
            "display_name": "Nexora Freight and Logistics",
            "tenant_code": "nexora-logistics",
            "registration_number": SEED_REGISTRATION_NUMBERS["nexora"],
            "industry": "Logistics and Transportation",
            "country": "India",
            "currency": "INR",
            "timezone": "Asia/Kolkata",
            "status": "active",
            "is_demo_tenant": True,
        },
        "profile": {
            "sector": "Industrials",
            "sub_sector": "Integrated Logistics",
            "employee_count": 620,
            "annual_revenue": "1850000000.00",
            "listed_status": "Private",
            "stock_exchange": "",
            "description": "Fictional logistics provider used to validate tenant isolation and read-only operational access.",
        },
        "departments": [
            ("Operations", "Fleet coordination, freight movement, terminal operations, and customer delivery execution."),
            ("Compliance", "Transport compliance, safety controls, regulatory reporting, and ESG oversight."),
        ],
        "organization_units": [
            {
                "name": "Nexora Corporate Office",
                "parent": None,
                "unit_type": "Corporate Headquarters",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
            },
            {
                "name": "South India Logistics Region",
                "parent": "Nexora Corporate Office",
                "unit_type": "Regional Logistics Operations",
                "country": "India",
                "state": "Tamil Nadu",
                "city": "Chennai",
            },
        ],
        "facilities": [
            {
                "name": "Chennai Freight Terminal",
                "organization_unit": "South India Logistics Region",
                "facility_type": "Freight Terminal",
                "country": "India",
                "state": "Tamil Nadu",
                "city": "Chennai",
            },
            {
                "name": "Bengaluru Distribution Warehouse",
                "organization_unit": "South India Logistics Region",
                "facility_type": "Warehouse",
                "country": "India",
                "state": "Karnataka",
                "city": "Bengaluru",
            },
        ],
        "roles": {
            "Company Admin": {
                "description": "Full-access tenant administrator responsible for company configuration and user administration.",
                "is_system_role": True,
                "permissions": list(CANONICAL_PERMISSION_CODES),
            },
            "Logistics Read-Only Operator": {
                "description": "Tenant-wide read-only access to departments, organization units, and facilities for isolation testing.",
                "permissions": [
                    "departments.view",
                    "organization_units.view",
                    "facilities.view",
                ],
            },
        },
        "users": [
            {
                "email": "priya.nair@nexora-demo.invalid",
                "employee_code": "NFL-ADM-001",
                "first_name": "Priya",
                "last_name": "Nair",
                "phone": "+91-90000-00101",
                "department": "Operations",
                "is_company_admin": True,
                "roles": [{"name": "Company Admin"}],
            },
            {
                "email": "karan.shah@nexora-demo.invalid",
                "employee_code": "NFL-CMP-017",
                "first_name": "Karan",
                "last_name": "Shah",
                "phone": "+91-90000-00102",
                "department": "Compliance",
                "roles": [{"name": "Logistics Read-Only Operator"}],
            },
        ],
    },
}


class Command(BaseCommand):
    help = "Seed two realistic fictional tenants and current Module 1 RBAC/scope data for development testing."

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
        self.stdout.write(self.style.SUCCESS("Seeded realistic Module 1 demo data."))
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
