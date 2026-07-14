from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

from accounts.models import UserAccount, UserRole

SCOPE_TYPE_ORG_UNIT = "ORG_UNIT"
SCOPE_TYPE_FACILITY = "FACILITY"


def _normalize_values(values) -> frozenset[str]:
    if values is None:
        return frozenset()
    if isinstance(values, (str, UUID)):
        return frozenset({str(values)})
    return frozenset(str(value) for value in values if value is not None)


@dataclass(frozen=True)
class ResourceContext:
    """Holds scope ids for authorization checks."""

    values_by_scope_type: dict[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, object] | None = None):
        if not mapping:
            return cls()
        return cls(
            values_by_scope_type={
                scope_type.upper(): _normalize_values(values)
                for scope_type, values in mapping.items()
            }
        )

    def values_for(self, scope_type: str) -> frozenset[str]:
        return self.values_by_scope_type.get(scope_type.upper(), frozenset())


def get_active_user_role_assignments(user: UserAccount):
    """Return active role assignments."""

    return UserRole.objects.select_related("role").filter(
        user=user,
        role__company=user.company,
        role__is_active=True,
    ).order_by("assigned_at", "id")


def get_active_roles(user: UserAccount):
    """Return active roles."""

    return [assignment.role for assignment in get_active_user_role_assignments(user)]


def _normalize_permission_codes(permission_codes: str | Iterable[str]) -> tuple[str, ...]:
    if isinstance(permission_codes, str):
        return (permission_codes,)
    return tuple(permission_codes)


def get_assignments_granting_permission(
    user: UserAccount,
    permission_codes: str | Iterable[str],
):
    codes = _normalize_permission_codes(permission_codes)
    return get_active_user_role_assignments(user).filter(
        role__role_permissions__permission__code__in=codes,
    ).prefetch_related("scopes").distinct()


def has_permission_assignment(
    user: UserAccount,
    permission_codes: str | Iterable[str],
) -> bool:
    return get_assignments_granting_permission(user, permission_codes).exists()


def _assignment_is_authorized(user_role: UserRole, resource_context: ResourceContext) -> bool:
    scopes = list(user_role.scopes.all())
    if not scopes:
        return True

    scope_groups: dict[str, set[str]] = defaultdict(set)
    for scope in scopes:
        scope_groups[scope.scope_type.upper()].add(str(scope.scope_id))

    for scope_type, allowed_scope_ids in scope_groups.items():
        context_ids = resource_context.values_for(scope_type)
        if not context_ids or allowed_scope_ids.isdisjoint(context_ids):
            return False

    return True


def authorize(
    user: UserAccount,
    permission_codes: str | Iterable[str],
    resource_context: ResourceContext | Mapping[str, object] | None = None,
    *,
    is_company_admin: bool = False,
) -> bool:
    """Check permissions against roles and scopes."""

    if is_company_admin:
        return True

    context = (
        resource_context
        if isinstance(resource_context, ResourceContext)
        else ResourceContext.from_mapping(resource_context)
    )
    codes = _normalize_permission_codes(permission_codes)
    candidate_assignments = get_assignments_granting_permission(user, codes)

    return any(
        _assignment_is_authorized(assignment, context)
        for assignment in candidate_assignments
    )


def filter_authorized_queryset(
    queryset,
    *,
    user: UserAccount,
    permission_codes: str | Iterable[str],
    resource_context_builder,
    is_company_admin: bool = False,
):
    """Filter a queryset by authorization."""

    if is_company_admin:
        return queryset

    authorized_ids = [
        obj.pk
        for obj in queryset
        if authorize(
            user,
            permission_codes,
            resource_context_builder(obj),
        )
    ]
    if not authorized_ids:
        return queryset.none()
    return queryset.filter(pk__in=authorized_ids)


def user_has_permission(user: UserAccount, permission_codes: str | Iterable[str]) -> bool:
    """Check permissions without a resource."""

    return authorize(user, permission_codes)
