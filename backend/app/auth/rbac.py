"""Role -> permission map and the `require_permission` route-guard dependency."""

from fastapi import Depends, HTTPException, status

from app.auth.deps import get_current_user
from app.models.user import User

PERMISSIONS = frozenset(
    {
        "read_vehicles",
        "write_service",
        "run_predict",
        "use_assistant",
        "read_own_vehicles",
        "manage_own",
        "read_only",
        "use_assistant_replay",
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "admin": PERMISSIONS,
    "mechanic": frozenset({"read_vehicles", "write_service", "run_predict", "use_assistant"}),
    "owner": frozenset({"read_own_vehicles", "manage_own"}),
    "demo": frozenset({"read_only", "use_assistant_replay"}),
}


def require_permission(*perms: str):
    """
    Build a FastAPI dependency that 403s unless the current user's role
    grants at least one of ``perms``. Returns the resolved ``User`` so route
    handlers needing it for owner-scoping can depend on this directly
    instead of also depending on ``get_current_user``.
    """

    async def _check(current_user: User = Depends(get_current_user)) -> User:
        allowed = ROLE_PERMISSIONS.get(current_user.role, frozenset())
        if not any(perm in allowed for perm in perms):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return _check
