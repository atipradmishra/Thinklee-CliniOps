from flask_jwt_extended import get_jwt_identity
from functools import wraps
from flask import session, abort
from app.models.user import User

def roles_required(*allowed_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_roles = session.get('roles', [])
            if not any(role in user_roles for role in allowed_roles):
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def org_admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = User.query.get(get_jwt_identity())
        if not user or not user.has_role('org_admin'):
            return {"message": "Unauthorized"}, 403
        return fn(*args, **kwargs)
    
    return wrapper
