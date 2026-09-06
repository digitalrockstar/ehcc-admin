import os
import secrets
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# auto_error=False: without this, FastAPI 401s on a missing Authorization
# header before require_admin() ever runs, which breaks the "auth is
# skipped when env vars are unset" local-dev path entirely.
security = HTTPBasic(auto_error=False)


def require_admin(request: Request, credentials: HTTPBasicCredentials = Depends(security)):
    """HTTP Basic Auth with two tiers, both from env vars:
    - ADMIN_USERNAME/ADMIN_PASSWORD: full read+write access.
    - VIEW_ACCESS_USER/VIEW_ACCESS_PWD: read-only. Any GET is allowed;
      any mutating request (POST/PUT/DELETE) gets a 403.

    If ADMIN_USERNAME/ADMIN_PASSWORD are not set, auth is skipped entirely -
    keeps local dev frictionless, but production MUST set both.
    """
    admin_user = os.getenv("ADMIN_USERNAME")
    admin_pass = os.getenv("ADMIN_PASSWORD")
    if not admin_user or not admin_pass:
        return True

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    is_admin = (
        secrets.compare_digest(credentials.username, admin_user)
        and secrets.compare_digest(credentials.password, admin_pass)
    )
    if is_admin:
        return True

    view_user = os.getenv("VIEW_ACCESS_USER")
    view_pass = os.getenv("VIEW_ACCESS_PWD")
    is_viewer = (
        view_user and view_pass
        and secrets.compare_digest(credentials.username, view_user)
        and secrets.compare_digest(credentials.password, view_pass)
    )
    if is_viewer:
        if request.method in ("GET", "HEAD"):
            return True
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="View-only access - this action requires admin login.")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Basic"},
    )
