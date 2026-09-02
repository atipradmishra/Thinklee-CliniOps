from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.models.user import User, Role
from app.extensions import db, bcrypt
from datetime import datetime
from functools import wraps

admin_bp = Blueprint('admin', __name__)

def super_admin_required(f):
    """Decorator to ensure only super admins can access the endpoint"""
    @wraps(f)
    @jwt_required()
    def decorated_function(*args, **kwargs):
        current_user_id = get_jwt_identity()
        current_user = User.query.get(current_user_id)
        
        if not current_user or not current_user.is_super_admin():
            return jsonify({'error': 'Super admin access required'}), 403
        
        return f(*args, **kwargs)
    return decorated_function

@admin_bp.route('/users', methods=['GET'])
@super_admin_required
def get_all_users():
    """Get all users with pagination"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    users = User.query.paginate(
        page=page, 
        per_page=per_page, 
        error_out=False
    )
    
    return jsonify({
        'users': [user.to_dict() for user in users.items],
        'total': users.total,
        'pages': users.pages,
        'current_page': page
    })

@admin_bp.route('/users/<int:user_id>', methods=['GET'])
@super_admin_required
def get_user(user_id):
    """Get a specific user by ID"""
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())

@admin_bp.route('/users', methods=['POST'])
@super_admin_required
def create_user():
    """Create a new user"""
    data = request.get_json()
    
    # Validate required fields
    required_fields = ['username', 'email', 'password']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'{field} is required'}), 400
    
    # Check if user already exists
    if User.query.filter_by(username=data['username']).first():
        return jsonify({'error': 'Username already exists'}), 400
    
    if User.query.filter_by(email=data['email']).first():
        return jsonify({'error': 'Email already exists'}), 400
    
    # Hash password
    hashed_password = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    
    # Create user
    user = User(
        username=data['username'],
        email=data['email'],
        password=hashed_password,
        token_quota=data.get('token_quota', 100000),
        status=data.get('status', 'active')
    )
    
    # Add roles if specified
    if 'roles' in data:
        for role_name in data['roles']:
            role = Role.query.filter_by(name=role_name).first()
            if role:
                user.roles.append(role)
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify({
        'message': 'User created successfully',
        'user': user.to_dict()
    }), 201

@admin_bp.route('/users/<int:user_id>', methods=['PUT'])
@super_admin_required
def update_user(user_id):
    """Update an existing user"""
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    
    # Check if username/email conflicts with other users
    if 'username' in data and data['username'] != user.username:
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'error': 'Username already exists'}), 400
        user.username = data['username']
    
    if 'email' in data and data['email'] != user.email:
        if User.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already exists'}), 400
        user.email = data['email']
    
    # Update password if provided
    if 'password' in data:
        user.password = bcrypt.generate_password_hash(data['password']).decode('utf-8')
    
    # Update other fields
    if 'token_quota' in data:
        user.token_quota = data['token_quota']
    
    if 'tokens_used_today' in data:
        user.tokens_used_today = data['tokens_used_today']
    
    if 'status' in data:
        user.status = data['status']
    
    if 'trial_expires_at' in data:
        if data['trial_expires_at']:
            user.trial_expires_at = datetime.fromisoformat(data['trial_expires_at'])
        else:
            user.trial_expires_at = None
    
    # Update roles if specified
    if 'roles' in data:
        user.roles.clear()
        for role_name in data['roles']:
            role = Role.query.filter_by(name=role_name).first()
            if role:
                user.roles.append(role)
    
    db.session.commit()
    
    return jsonify({
        'message': 'User updated successfully',
        'user': user.to_dict()
    })

@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@super_admin_required
def delete_user(user_id):
    """Delete a user"""
    current_user_id = get_jwt_identity()
    
    # Prevent self-deletion
    if user_id == current_user_id:
        return jsonify({'error': 'Cannot delete your own account'}), 400
    
    user = User.query.get_or_404(user_id)
    
    # Prevent deletion of other super admins (optional security measure)
    if user.is_super_admin():
        return jsonify({'error': 'Cannot delete super admin accounts'}), 400
    
    db.session.delete(user)
    db.session.commit()
    
    return jsonify({'message': 'User deleted successfully'})

@admin_bp.route('/users/search', methods=['GET'])
@super_admin_required
def search_users():
    """Search users by username or email"""
    query = request.args.get('q', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    
    if not query:
        return jsonify({'error': 'Search query is required'}), 400
    
    users = User.query.filter(
        db.or_(
            User.username.contains(query),
            User.email.contains(query)
        )
    ).paginate(
        page=page,
        per_page=per_page,
        error_out=False
    )
    
    return jsonify({
        'users': [user.to_dict() for user in users.items],
        'total': users.total,
        'pages': users.pages,
        'current_page': page,
        'query': query
    })

@admin_bp.route('/roles', methods=['GET'])
@super_admin_required
def get_all_roles():
    """Get all available roles"""
    roles = Role.query.all()
    return jsonify({
        'roles': [{'id': role.id, 'name': role.name, 'description': role.description} for role in roles]
    })

@admin_bp.route('/stats', methods=['GET'])
@super_admin_required
def get_admin_stats():
    """Get admin dashboard statistics"""
    total_users = User.query.count()
    active_users = User.query.filter_by(status='active').count()
    inactive_users = total_users - active_users
    
    # Users by role
    roles_stats = []
    for role in Role.query.all():
        user_count = role.users.count()
        roles_stats.append({
            'role': role.name,
            'count': user_count
        })
    
    return jsonify({
        'total_users': total_users,
        'active_users': active_users,
        'inactive_users': inactive_users,
        'roles_distribution': roles_stats
    })
