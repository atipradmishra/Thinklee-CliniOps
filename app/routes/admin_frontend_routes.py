from app.models.table_metadata import TableMetadata
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from app.models.user import User, Role
from app.extensions import db, bcrypt
from datetime import datetime
from functools import wraps
import pandas as pd
from flask import send_file
from io import BytesIO

admin_frontend_bp = Blueprint('admin_frontend', __name__)

def admin_login_required(f):
    """Decorator to ensure only logged-in super admins can access admin pages"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_user_id' not in session:
            return redirect(url_for('admin_frontend.login'))
        
        user = User.query.get(session['admin_user_id'])
        if not user or not user.is_super_admin():
            session.pop('admin_user_id', None)
            flash('Access denied. Super admin privileges required.', 'error')
            return redirect(url_for('admin_frontend.login'))
        
        return f(*args, **kwargs)
    return decorated_function

@admin_frontend_bp.route('/admin/')
def index():
    return redirect(url_for('admin_frontend.login'))

@admin_frontend_bp.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and bcrypt.check_password_hash(user.password, password):
            if user.is_super_admin():
                session['admin_user_id'] = user.id
                flash('Login successful!', 'success')
                return redirect(url_for('admin_frontend.dashboard'))
            else:
                flash('Access denied. Super admin privileges required.', 'error')
        else:
            flash('Invalid username or password.', 'error')
    
    return render_template('admin/login.html')

@admin_frontend_bp.route('/admin/logout')
def logout():
    session.pop('admin_user_id', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('admin_frontend.login'))

@admin_frontend_bp.route('/admin/dashboard')
@admin_login_required
def dashboard():
    # Get statistics
    total_users = User.query.count()
    active_users = User.query.filter_by(status='active').count()
    inactive_users = total_users - active_users
    
    # Get role distribution
    roles_stats = []
    roles = Role.query.all()
    for role in roles:
        user_count = role.users.count()
        roles_stats.append({
            'role': role.name,
            'count': user_count
        })
    
    stats = {
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'roles_distribution': roles_stats
    }
    
    return render_template('admin/dashboard.html', stats=stats, roles=roles)

@admin_frontend_bp.route('/admin/users')
@admin_login_required
def users():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    search = request.args.get('search', '')
    
    query = User.query
    if search:
        query = query.filter(
            db.or_(
                User.username.contains(search),
                User.email.contains(search)
            )
        )
    
    users = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    current_user = User.query.get(session['admin_user_id'])
    
    return render_template('admin/users.html', users=users, current_user=current_user)

@admin_frontend_bp.route('/admin/users/<int:user_id>')
@admin_login_required
def user_detail(user_id):
    user = User.query.get_or_404(user_id)
    return render_template('admin/user_detail.html', user=user)

@admin_frontend_bp.route('/admin/users/create', methods=['GET', 'POST'])
@admin_login_required
def create_user():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        token_quota = request.form.get('token_quota', 100000, type=int)
        tokens_used_today = request.form.get('tokens_used_today', 0, type=int)
        status = request.form.get('status')
        trial_expires_at = request.form.get('trial_expires_at')
        selected_roles = request.form.getlist('roles')
        
        # Validation
        if User.query.filter_by(username=username).first():
            flash('Username already exists.', 'error')
            return render_template('admin/user_form.html', available_roles=Role.query.all())
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists.', 'error')
            return render_template('admin/user_form.html', available_roles=Role.query.all())
        
        # Create user
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(
            username=username,
            email=email,
            password=hashed_password,
            token_quota=token_quota,
            tokens_used_today=tokens_used_today,
            status=status
        )
        
        # Set trial expiry
        if trial_expires_at:
            user.trial_expires_at = datetime.fromisoformat(trial_expires_at)
        
        # Add roles
        for role_name in selected_roles:
            role = Role.query.filter_by(name=role_name).first()
            if role:
                user.roles.append(role)
        
        db.session.add(user)
        db.session.commit()
        
        flash(f'User {username} created successfully!', 'success')
        return redirect(url_for('admin_frontend.users'))
    
    available_roles = Role.query.all()
    return render_template('admin/user_form.html', available_roles=available_roles)

@admin_frontend_bp.route("/users/download")
@admin_login_required   
def download_users():
    users = User.query.all()
    data = []
    for user in users:
        data.append({
            "ID": user.id,
            "Username": user.username,
            "Email": user.email,
            "Status": "Active" if user.status == "active" else "Inactive",
            "Roles": ", ".join([role.name for role in user.roles]),
            "Created At": user.created_at.strftime("%Y-%m-%d")
        })

    df = pd.DataFrame(data)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Users")

    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name="users.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@admin_frontend_bp.route('/admin/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_login_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        token_quota = request.form.get('token_quota', type=int)
        tokens_used_today = request.form.get('tokens_used_today', type=int)
        status = request.form.get('status')
        trial_expires_at = request.form.get('trial_expires_at')
        selected_roles = request.form.getlist('roles')
        
        # Check for username conflicts
        if username != user.username and User.query.filter_by(username=username).first():
            flash('Username already exists.', 'error')
            return render_template('admin/user_form.html', user=user, available_roles=Role.query.all())
        
        # Check for email conflicts
        if email != user.email and User.query.filter_by(email=email).first():
            flash('Email already exists.', 'error')
            return render_template('admin/user_form.html', user=user, available_roles=Role.query.all())
        
        # Update user
        user.username = username
        user.email = email
        user.token_quota = token_quota
        user.tokens_used_today = tokens_used_today
        user.status = status
        
        # Update password if provided
        if password:
            user.password = bcrypt.generate_password_hash(password).decode('utf-8')
        
        # Update trial expiry
        if trial_expires_at:
            user.trial_expires_at = datetime.fromisoformat(trial_expires_at)
        else:
            user.trial_expires_at = None
        
        # Update roles
        user.roles.clear()
        for role_name in selected_roles:
            role = Role.query.filter_by(name=role_name).first()
            if role:
                user.roles.append(role)
        
        db.session.commit()
        
        flash(f'User {username} updated successfully!', 'success')
        return redirect(url_for('admin_frontend.user_detail', user_id=user.id))
    
    available_roles = Role.query.all()
    return render_template('admin/user_form.html', user=user, available_roles=available_roles)

@admin_frontend_bp.route('/admin/users/<int:user_id>/delete', methods=['POST'])
@admin_login_required
def delete_user(user_id):
    current_user_id = session['admin_user_id']
    
    # Prevent self-deletion
    if user_id == current_user_id:
        flash('Cannot delete your own account.', 'error')
        return redirect(url_for('admin_frontend.users'))
    
    user = User.query.get_or_404(user_id)
    
    # Prevent deletion of super admins
    if user.is_super_admin():
        flash('Cannot delete super admin accounts.', 'error')
        return redirect(url_for('admin_frontend.users'))
    
    username = user.username
    db.session.delete(user)
    db.session.commit()
    
    flash(f'User {username} deleted successfully.', 'success')
    return redirect(url_for('admin_frontend.users'))



@admin_frontend_bp.route('/admin/tables')
@admin_login_required
def tables():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    search = request.args.get('search', '')
    
    query = TableMetadata.query
    if search:
        query = query.filter(
            db.or_(
                User.username.contains(search),
                User.email.contains(search)
            )
        )
    
    tables = query.paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    current_user = User.query.get(session['admin_user_id'])
    
    return render_template('admin/tables.html', tables=tables, current_user=current_user)

@admin_frontend_bp.route('/admin/tables/<int:table_id>')
@admin_login_required
def table_detail(table_id):
    table = TableMetadata.query.get(table_id)
    if not table:
        abort(404, "Table not found")

    return render_template("admin/table_detail.html", table=table)