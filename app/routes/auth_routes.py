from flask import Blueprint
from app.controllers import auth_controller

auth_bp = Blueprint('auth_bp', __name__)

auth_bp.route('/register', methods=['POST'])(auth_controller.register)
auth_bp.route('/send-otp', methods=['POST'])(auth_controller.send_otp)
auth_bp.route('/verify-otp', methods=['POST'])(auth_controller.verify_login_otp)
auth_bp.route('/verify-temp-password', methods=['POST'])(auth_controller.verify_temp_password)
auth_bp.route('/reset-password', methods=['POST'])(auth_controller.reset_password)
auth_bp.route('/login', methods=['POST'])(auth_controller.login)
auth_bp.route('/logout', methods=['POST'])(auth_controller.logout)
auth_bp.route('/me', methods=['GET'])(auth_controller.me)
