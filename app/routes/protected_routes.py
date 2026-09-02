from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required
from app.utils.decorators import role_required

protected_bp = Blueprint('protected_bp', __name__)

@protected_bp.route('/user-dashboard', methods=['GET'])
@jwt_required()
@role_required('user')
def user_dashboard():
    return jsonify({"msg": "Welcome, User! Here's your dashboard."})

@protected_bp.route('/admin-dashboard', methods=['GET'])
@jwt_required()
@role_required('admin')
def admin_dashboard():
    return jsonify({"msg": "Welcome, Admin! Here's the admin panel."})
