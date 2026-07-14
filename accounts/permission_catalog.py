from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass


CATALOG_ACTION_ORDER = ("View", "Create", "Edit", "Update")
CANONICAL_PERMISSION_MATRIX = OrderedDict(
    [
        (
            "Users",
            OrderedDict(
                [
                    ("View", "users.view"),
                    ("Create", "users.create"),
                    ("Edit", "users.edit"),
                    ("Update", "users.update"),
                ]
            ),
        ),
        (
            "Roles",
            OrderedDict(
                [
                    ("View", "roles.view"),
                    ("Create", "roles.create"),
                    ("Edit", "roles.edit"),
                    ("Update", "roles.update"),
                ]
            ),
        ),
        (
            "Departments",
            OrderedDict(
                [
                    ("View", "departments.view"),
                    ("Create", "departments.create"),
                    ("Edit", "departments.edit"),
                    ("Update", "departments.update"),
                ]
            ),
        ),
        (
            "Organization Units",
            OrderedDict(
                [
                    ("View", "organization_units.view"),
                    ("Create", "organization_units.create"),
                    ("Edit", "organization_units.edit"),
                    ("Update", "organization_units.update"),
                ]
            ),
        ),
        (
            "Facilities",
            OrderedDict(
                [
                    ("View", "facilities.view"),
                    ("Create", "facilities.create"),
                    ("Edit", "facilities.edit"),
                    ("Update", "facilities.update"),
                ]
            ),
        ),
    ]
)


@dataclass(frozen=True)
class PermissionSpec:
    code: str
    name: str
    module: str
    description: str = ""

    @property
    def defaults(self) -> dict[str, str]:
        return {
            "name": self.name,
            "module": self.module,
            "description": self.description,
        }


CANONICAL_PERMISSION_SPECS = tuple(
    PermissionSpec(
        code=code,
        name=f"{action} {module.lower()}",
        module=module,
        description=f"Allows a tenant role to {action.lower()} {module.lower()}.",
    )
    for module, actions in CANONICAL_PERMISSION_MATRIX.items()
    for action, code in actions.items()
)
CANONICAL_PERMISSION_CODES = tuple(spec.code for spec in CANONICAL_PERMISSION_SPECS)
CANONICAL_PERMISSION_CODES_SET = frozenset(CANONICAL_PERMISSION_CODES)


def sync_permission_catalog(*, permission_model=None, using=None) -> dict[str, int]:
    if permission_model is None:
        from accounts.models import Permission as permission_model

    manager = permission_model.objects
    if using is not None:
        manager = manager.using(using)

    created = 0
    updated = 0
    for spec in CANONICAL_PERMISSION_SPECS:
        _, was_created = manager.update_or_create(
            code=spec.code,
            defaults=spec.defaults,
        )
        if was_created:
            created += 1
        else:
            updated += 1
    return {"created": created, "updated": updated}


def get_permission_map(codes=None, *, permission_model=None, using=None):
    if permission_model is None:
        from accounts.models import Permission as permission_model

    selected_codes = tuple(codes or CANONICAL_PERMISSION_CODES)
    manager = permission_model.objects
    if using is not None:
        manager = manager.using(using)

    permissions = manager.in_bulk(selected_codes, field_name="code")
    missing_codes = [code for code in selected_codes if code not in permissions]
    if missing_codes:
        missing_list = ", ".join(missing_codes)
        raise LookupError(f"Missing canonical permissions: {missing_list}")
    return permissions
