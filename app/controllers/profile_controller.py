from os import abort
import string
from app.utils.email_utils import send_invite_email
from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from app.models.organization import Organization, OrganizationMember
from app.models.user import Role, User
from app.models.agent import Agent
from app.models.dashboard import Dashboard
from app.models.data_connection import DataSourceConnection
from app.models.file_metadata import FileMetadata
from app.models.query_log import QueryLog
from app.models.table_metadata import TableMetadata
import secrets
from datetime import datetime
from app.extensions import db, bcrypt

def hash_password(password):
    return bcrypt.generate_password_hash(password).decode('utf-8')

def generate_temp_password(length=12):
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))

def assign_role_to_user(user, role_name):
    role = Role.query.filter_by(name=role_name).first()
    if role and role not in user.roles:
        user.roles.append(role)
        db.session.commit()

def get_current_org_member(user_id):
    member = (
        OrganizationMember.query
        .filter_by(user_id=user_id)
        .first()
    )
    if not member:
        abort(403, "User not part of any organization")
    return member

def require_org_admin(member):
    if member.role not in ("org_admin",):
        abort(403, "Admin privileges required")




@jwt_required()
def post_organization_setup():
    user_id = get_jwt_identity()
    user = User.query.get(user_id)

    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    if user.org_setup_completed:
        return jsonify({
            "success": False,
            "message": "Organization setup already completed"
        }), 403

    data = request.form

    org_name = data.get("org_name", "").strip()
    time_zone = data.get("timezone")
    industry = data.get("industry")
    team_size = data.get("team_size")

    role = data.get("role", "org_user")
    role_name = data.get("role_name")
    employee_id = data.get("emp_id")

    if not org_name:
        return jsonify({"success": False, "message": "Organization name is required"}), 400

    if not time_zone:
        return jsonify({"success": False, "message": "Time zone is required"}), 400

    if not role_name:
        return jsonify({"success": False, "message": "Role name is required"}), 400

    if role not in ("org_admin", "org_user"):
        role = "org_user"

    try:
        existing_org = Organization.query.filter_by(name=org_name).first()
        if existing_org:
            return jsonify({
                "success": False,
                "message": "Organization already exists"
            }), 409

        org = Organization(
            name=org_name,
            time_zone=time_zone,
            industry=industry,
            team_size=team_size
        )
        db.session.add(org)
        db.session.flush()

        membership = OrganizationMember(
            organization_id=org.id,
            user_id=user.id,
            role=role,
            job_title=role_name,
            employee_id=employee_id
        )
        db.session.add(membership)

        user.organization_id = org.id
        user.org_setup_completed = True
        user.updated_at = datetime.now()

        if role == "org_admin":
            assign_role_to_user(user, "org_admin")
        elif role == "org_user":
            assign_role_to_user(user, "org_user")
        else:
            assign_role_to_user(user, "user")

        db.session.commit()
        db.session.refresh(user)

        return jsonify({
            "success": True,
            "organization": {
                "id": org.id,
                "name": org.name
            },
            "role": membership.role,
            "org_setup_completed": True
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "success": False,
            "message": "Organization setup failed",
            "error": str(e)
        }), 500

@jwt_required()
def get_user_profile():
    user_id = get_jwt_identity()

    user = User.query.get(user_id)
    print(user.last_login)
    if not user:
        return jsonify({"error": "User not found"}), 404

    org_member = (
        OrganizationMember.query
        .filter_by(user_id=user.id)
        .first()
    )

    org_data = None
    if org_member:
        org = org_member.organization
        org_data = {
            "id": org.id,
            "name": org.name,
            "plan": org.plan,
            "job_title": org_member.job_title,
            "joined_at": org_member.joined_at.isoformat()
        }

    return jsonify({
        "user": {
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "contact_number": user.contact_number,
            "profile_pic_url": user.profile_pic_url,
            "status": user.status,
            "trial_expires_at": user.trial_expires_at.isoformat() if user.trial_expires_at else None,
            "token_quota": user.token_quota,
            "tokens_used_today": user.tokens_used_today,
            "last_login": user.last_login.isoformat() if user.last_login else None,
            "created_at": user.created_at.isoformat()
        },
        "organization": org_data
    }), 200

@jwt_required()
def complete_tour():
    """Mark the product tour as seen.

    Called when the user finishes the last step or dismisses the tour; both
    count as "seen" so it does not reappear on the next login.
    """
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    if user.tour_completed_at is None:
        user.tour_completed_at = datetime.now()
        db.session.commit()

    return jsonify({
        "success": True,
        "tour_completed_at": user.tour_completed_at.isoformat()
    }), 200


@jwt_required()
def reset_tour():
    """Clear the tour flag so the walkthrough can be replayed."""
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    user.tour_completed_at = None
    db.session.commit()

    return jsonify({"success": True, "message": "Tour reset"}), 200


@jwt_required()
def get_setup_progress():
    """Real setup progress for the onboarding checklist.

    The /steps page previously rendered hardcoded sample data; these counts
    come from the user's actual organization.
    """
    user = User.query.get(get_jwt_identity())
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    org_id = user.organization_id

    connections = DataSourceConnection.query.filter_by(
        organization_id=org_id, is_deleted=False).count()
    tables = TableMetadata.query.filter_by(
        organization_id=org_id, is_deleted=False).count()
    files = FileMetadata.query.filter_by(
        organization_id=org_id, is_deleted=False).count()
    agents = Agent.query.filter_by(
        organization_id=org_id, is_deleted=False).count()
    queries = QueryLog.query.filter_by(organization_id=org_id).count()
    dashboards = Dashboard.query.filter_by(organization_id=org_id).count()

    has_data = bool(connections or tables or files)

    # Shape matches what steps.html already renders.
    definitions = [
        {
            "title": "Connect Data Source",
            "description": "Link a database — PostgreSQL, MySQL, SQL Server, Snowflake, "
                           "AWS RDS or Azure SQL — or upload CSV, Excel and documents.",
            "icon": "fas fa-database",
            "action_url": "/data-management",
            "done": has_data,
            "detail": f"{connections} connection(s), {tables} table(s), {files} file(s)",
        },
        {
            "title": "Create AI Agent",
            "description": "Point an agent at specific tables or documents and tune how it answers.",
            "icon": "fas fa-robot",
            "action_url": "/agent-management",
            "done": agents > 0,
            "detail": f"{agents} agent(s)",
        },
        {
            "title": "Run Natural Language Queries",
            "description": "Ask questions in plain language through Co-Pilot and get explained answers.",
            "icon": "fas fa-comments",
            "action_url": "/copilot-page",
            "done": queries > 0,
            "detail": f"{queries} question(s) asked",
        },
        {
            "title": "Configure Dashboard",
            "description": "Save your most useful questions as widgets on a shareable dashboard.",
            "icon": "fas fa-chart-line",
            "action_url": "/dashboard/builder",
            "done": dashboards > 0,
            "detail": f"{dashboards} dashboard(s)",
        },
    ]

    steps = []
    current_assigned = False
    for position, item in enumerate(definitions, start=1):
        if item["done"]:
            status = "completed"
        elif not current_assigned:
            status = "current"
            current_assigned = True
        else:
            status = "pending"

        steps.append({
            "id": position,
            "title": item["title"],
            "description": item["description"],
            "status": status,
            "icon": item["icon"],
            "detail": item["detail"],
            "action_text": "Review" if item["done"] else "Start",
            "action_url": item["action_url"],
        })

    completed = sum(1 for s in steps if s["status"] == "completed")
    in_progress = sum(1 for s in steps if s["status"] == "current")

    return jsonify({
        "success": True,
        "user": {
            "name": user.first_name or user.username,
            "email": user.email,
        },
        "progress": {
            "percentage": round(completed / len(steps) * 100),
            "completed_steps": completed,
            "in_progress_steps": in_progress,
            "remaining_steps": len(steps) - completed - in_progress,
        },
        "steps": steps,
        "tour_completed": user.tour_completed_at is not None,
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }), 200


@jwt_required()
def update_user_profile():
    user_id = get_jwt_identity()
    user = User.query.get_or_404(user_id)

    data = request.get_json() or {}

    # ======================
    # Update User fields
    # ======================
    user.first_name = data.get("first_name", user.first_name)
    user.last_name = data.get("last_name", user.last_name)

    # Email update (safe)
    new_email = data.get("email")
    if new_email and new_email != user.email:
        email_exists = User.query.filter_by(email=new_email).first()
        if email_exists:
            return jsonify({
                "status": "error",
                "message": "Email already in use"
            }), 409
        user.email = new_email

    user.contact_number = data.get("phone", user.contact_number)

    # ======================
    # Update Organization Member fields
    # ======================
    org_member = (
        OrganizationMember.query
        .filter_by(user_id=user.id)
        .first()
    )

    if org_member:
        org_member.job_title = data.get(
            "job_title",
            org_member.job_title
        )

        # Optional: allow org_admin to rename org
        if data.get("company"):
            if org_member.role == "org_admin":
                org_member.organization.name = data["company"]

    db.session.commit()

    return jsonify({
        "status": "success",
        "message": "Profile updated successfully"
    }), 200

@jwt_required()
def get_org_users():
    user_id = get_jwt_identity()
    member = get_current_org_member(user_id)

    org = member.organization

    members = (
        OrganizationMember.query
        .join(User)
        .filter(OrganizationMember.organization_id == org.id)
        .all()
    )

    users = []
    for m in members:
        u = m.user
        users.append({
            "id": u.id,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "email": u.email,
            "role": m.role.replace("org_", ""), 
            "status": u.status,
            "last_active": u.last_login.isoformat() if u.last_login else None,
            "joined": m.joined_at.isoformat(),
            "avatar": u.profile_pic_url or
                f"https://ui-avatars.com/api/?name={u.first_name}+{u.last_name}&size=80"
        })

    return jsonify({"users": users})

@jwt_required()
def invite_user():
    print("Inviting user...")
    admin = get_current_org_member(get_jwt_identity())
    require_org_admin(admin)

    data = request.get_json()
    email = data["email"]
    role = f"org_{data['role']}"
    message = data["message"] if "message" in data else ''

    print(message)

    if User.query.filter_by(email=email).first():
        return jsonify({"message": "User already exists"}), 409

    temp_password = generate_temp_password()

    user = User(
        email=email,
        username=email,
        password=hash_password(temp_password),
        status="pending",
        must_reset_password=True,
        org_setup_completed=True,
        organization_id=admin.organization_id
    )
    db.session.add(user)
    db.session.flush()

    member = OrganizationMember(
        user_id=user.id,
        organization_id=admin.organization_id,
        role=role
    )

    if role == "org_admin":
            assign_role_to_user(user, "org_admin")
    elif role == "org_user":
            assign_role_to_user(user, "org_user")
    else:
            assign_role_to_user(user, "user")
    
    db.session.add(member)
    db.session.commit()
    print("User invited successfully")
    send_invite_email(
        email=email,
        org_name=admin.organization.name,
        password=temp_password,
        login_url=f"{request.host_url}reset-password",
        message = message
    )
    print(f"Sent invite to {email}")

    return jsonify({"message": "User invited successfully"}), 201

@jwt_required()
def update_user(user_id):
    admin = get_current_org_member(get_jwt_identity())
    require_org_admin(admin)

    member = OrganizationMember.query.filter_by(
        user_id=user_id,
        organization_id=admin.organization_id
    ).first_or_404()

    data = request.get_json()
    member.role = f"org_{data['role']}"

    db.session.commit()
    return jsonify({"message": "User updated"})

@jwt_required()
def remove_user(user_id):
    admin = get_current_org_member(get_jwt_identity())
    require_org_admin(admin)

    member = OrganizationMember.query.filter_by(
        user_id=user_id,
        organization_id=admin.organization_id
    ).first_or_404()

    db.session.delete(member)
    db.session.commit()

    return jsonify({"message": "User removed"})

@jwt_required()
def bulk_update_role():
    admin = get_current_org_member(get_jwt_identity())
    require_org_admin(admin)

    data = request.get_json()
    role = f"org_{data['role']}"

    OrganizationMember.query.filter(
        OrganizationMember.user_id.in_(data["user_ids"]),
        OrganizationMember.organization_id == admin.organization_id
    ).update(
        {"role": role},
        synchronize_session=False
    )

    db.session.commit()
    return jsonify({"message": "Roles updated"})

@jwt_required()
def bulk_remove_users():
    admin = get_current_org_member(get_jwt_identity())
    require_org_admin(admin)

    OrganizationMember.query.filter(
        OrganizationMember.user_id.in_(request.json["user_ids"]),
        OrganizationMember.organization_id == admin.organization_id
    ).delete(synchronize_session=False)

    db.session.commit()
    return jsonify({"message": "Users removed"})

@jwt_required()
def bulk_resend_invites():
    admin = get_current_org_member(get_jwt_identity())
    require_org_admin(admin)

    users = User.query.filter(
        User.id.in_(request.json["user_ids"]),
        User.status == "pending"
    ).all()

    for u in users:
        pass  # resend email

    return jsonify({"message": "Invites resent"})
