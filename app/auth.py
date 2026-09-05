import os
import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

# auto_error=False: without this, FastAPI 401s on a missing Authorization
# header before require_admin() ever runs, which breaks the "auth is
# skipped when env vars are unset" local-dev path entirely.
security = HTTPBasic(auto_error=False)


def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    """Single-admin HTTP Basic Auth. Credentials come from env vars so
    nothing sensitive lives in code or git history.

    If ADMIN_USERNAME/ADMIN_PASSWORD are not set, auth is skipped - this
    keeps local dev frictionless but means production deploys MUST set
    both env vars (documented in render.yaml and README).
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

    correct_user = secrets.compare_digest(credentials.username, admin_user)
    correct_pass = secrets.compare_digest(credentials.password, admin_pass)
    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True
