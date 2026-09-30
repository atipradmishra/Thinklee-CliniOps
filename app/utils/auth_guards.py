"""Session guards for server-rendered pages.

The JSON API is protected by ``@jwt_required()`` from flask_jwt_extended, but
page routes are reached by the browser navigating directly and carry no
Authorization header - they authenticate off the JWT stashed in the Flask
session at login. Before this module most page routes had no check at all, so
any URL could be opened by typing it.

Three guards:

``login_required``            authenticated + past onboarding
``login_required_no_setup``   authenticated only (for the setup page itself)
``redirect_if_authenticated`` bounce signed-in users off the landing/login pages
"""

from functools import wraps
from urllib.parse import urlparse

from flask import redirect, request, session, url_for
from flask_jwt_extended import decode_token

from app.models.user import User

LOGIN_ENDPOINT = "page_bp.auth_page"
HOME_PATH = "/home"
RESET_PATH = "/reset-password"
ORG_SETUP_PATH = "/org-setup"


def session_user():
    """Return the signed-in User, or None.

    Validates the JWT held in the session rather than trusting session['id']
    alone, so an expired token logs the user out instead of granting access
    until the cookie is cleared.
    """
    token = session.get("access_token")
    if not token:
        return None

    try:
        decoded = decode_token(token)
    except Exception:
        # Expired, malformed, or signed with a rotated key.
        return None

    user_id = decoded.get("sub")
    if not user_id:
        return None

    try:
        user = User.query.get(int(user_id))
    except (TypeError, ValueError):
        return None

    return user


def onboarding_redirect(user):
    """Where this user must go before using the app, or None if ready.

    Mirrors the cascade in auth_controller.login() so a user cannot skip a
    step by typing a later URL.
    """
    if user.must_reset_password:
        return RESET_PATH
    if not user.org_setup_completed:
        return ORG_SETUP_PATH
    return None


def landing_target(user):
    """The page a signed-in user should land on."""
    return onboarding_redirect(user) or HOME_PATH


def is_safe_next(target):
    """Only allow same-site relative paths, to avoid an open redirect."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return False
    if "\\" in target:
        return False
    parsed = urlparse(target)
    return not parsed.netloc and not parsed.scheme


def _to_login():
    """Send the visitor to sign in, remembering where they were headed."""
    nxt = request.full_path.rstrip("?") if request.method == "GET" else None
    if nxt and is_safe_next(nxt) and nxt != "/":
        return redirect(url_for(LOGIN_ENDPOINT, next=nxt))
    return redirect(url_for(LOGIN_ENDPOINT))


def login_required(fn):
    """Require a signed-in user who has finished onboarding."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = session_user()
        if not user:
            session.clear()
            return _to_login()

        pending = onboarding_redirect(user)
        if pending and request.path != pending:
            return redirect(pending)

        return fn(*args, **kwargs)
    return wrapper


def login_required_no_setup(fn):
    """Require a signed-in user, but allow organization setup to be pending.

    Used by /org-setup itself, which would otherwise redirect to itself.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = session_user()
        if not user:
            session.clear()
            return _to_login()

        if user.must_reset_password and request.path != RESET_PATH:
            return redirect(RESET_PATH)

        return fn(*args, **kwargs)
    return wrapper


def redirect_if_authenticated(fn):
    """Keep signed-in users off the landing and login pages."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = session_user()
        if user:
            nxt = request.args.get("next")
            if is_safe_next(nxt):
                return redirect(nxt)
            return redirect(landing_target(user))
        return fn(*args, **kwargs)
    return wrapper
