from app.utils.email_utils import generate_otp
from flask import request, jsonify, session
from app.extensions import db, bcrypt,  mail
from app.models.user import EmailOTP, User
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from flask_mail import Message
import requests

def register():
    data = request.get_json()
    password = data.get('password')
    email = data.get('email')
    otp = data.get('otp')

    # Check OTP
    email_otp = EmailOTP.query.filter_by(email=email, otp=otp).first()
    if not email_otp or email_otp.expires_at < datetime.now():
        return jsonify({'success': False, 'message': 'Invalid or expired OTP'}), 400

    # Create user
    hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
    trial_expires_at = datetime.now() + timedelta(days=15)
    new_user = User(username=email, password=hashed_pw, email=email, trial_expires_at=trial_expires_at, must_reset_password=False)

    db.session.add(new_user)
    db.session.delete(email_otp)
    db.session.commit()

    return jsonify({'success': True, 'message': 'User registered successfully'}), 201

def send_otp():
    data = request.get_json()
    email = data.get('email')

    if not email:
        return jsonify({'success': False, 'message': 'Email is required'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'message': 'Email already registered'}), 400

    # Remove old OTP if exists
    EmailOTP.query.filter_by(email=email).delete()

    otp = generate_otp()
    expires_at = datetime.now() + timedelta(minutes=5)

    new_otp = EmailOTP(email=email, otp=otp, expires_at=expires_at)
    db.session.add(new_otp)
    db.session.commit()

    # Send OTP email
    try:
        msg = Message("Thinklee OTP Verification", recipients=[email])
        msg.body = f"Your OTP is {otp}. It will expire in 5 minutes."
        mail.send(msg)
        return jsonify({'success': True, 'message': 'OTP sent successfully'}), 200
    except Exception as e:
        return jsonify({'success': False, 'message': f'Failed to send OTP: {str(e)}'}), 500

def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('password')

    user = User.query.filter_by(email=email).first()

    if user and bcrypt.check_password_hash(user.password, password):

        db.session.refresh(user)

        token = create_access_token(
            identity=str(user.id),
            expires_delta=timedelta(days=10)
        )

        session['id'] = user.id
        session['email'] = user.email
        session['username'] = user.username
        session['access_token'] = token
        session['roles'] = [role.name for role in user.roles]
        
        print(session['roles'])

        link = None
        org_setup_completed = user.org_setup_completed
        must_reset_password = user.must_reset_password
        if must_reset_password:
            link = "/reset-password"
        elif not org_setup_completed:
            link = "/org-setup"
        else:
            link = "/home"
        print(f"org_setup_completed: {org_setup_completed}")

        user.last_login = datetime.now()
        db.session.commit()

        return jsonify({
            'success': True,
            'access_token': token,
            'redirect_url': link
        }), 200

    return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

def verify_temp_password():
    data = request.get_json()

    email = data.get("email")
    temp_password = data.get("temp_password")

    if not email or not temp_password:
        return jsonify({
            "success": False,
            "message": "Email and temporary password are required"
        }), 400

    user = User.query.filter_by(email=email).first()

    if not user:
        return jsonify({
            "success": False,
            "message": "Invalid email or password"
        }), 401

    # if user.status != "pending":
    #     return jsonify({
    #         "success": False,
    #         "message": "User account is not active"
    #     }), 403

    if not user.must_reset_password:
        return jsonify({
            "success": False,
            "message": "Temporary password not applicable"
        }), 400

    if not bcrypt.check_password_hash(user.password, temp_password):
        return jsonify({
            "success": False,
            "message": "Invalid email or password"
        }), 401
    
    try:
        send_login_otp(email)
    except requests.RequestException as e:
        print(f"OTP send failed: {e}")


    return jsonify({
        "success": True,
        "message": "Temporary password verified",
        "reset_required": True
    }), 200

def send_login_otp(email):

    if not email:
        return jsonify({"success": False, "message": "Email required"}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not user.must_reset_password:
        return jsonify({"success": False, "message": "Unauthorized request"}), 403

    # Remove old OTP
    EmailOTP.query.filter_by(email=email).delete()

    otp = generate_otp()
    expires_at = datetime.now() + timedelta(minutes=5)

    db.session.add(EmailOTP(email=email, otp=otp, expires_at=expires_at))
    db.session.commit()

    try:
        msg = Message("Login OTP Verification", recipients=[email])
        msg.body = f"Your OTP is {otp}. It will expire in 5 minutes."
        mail.send(msg)

        return jsonify({
            "success": True,
            "message": "OTP sent successfully"
        }), 200

    except Exception as e:
        return jsonify({
            "success": False,
            "message": f"Failed to send OTP: {str(e)}"
        }), 500

def verify_login_otp():
    data = request.get_json()
    email = data.get("email")
    otp = data.get("otp")

    if not email or not otp:
        return jsonify({"success": False, "message": "Email and OTP required"}), 400

    record = EmailOTP.query.filter_by(email=email, otp=otp).first()

    if not record:
        return jsonify({"success": False, "message": "Invalid OTP"}), 401

    if record.expires_at < datetime.utcnow():
        db.session.delete(record)
        db.session.commit()
        return jsonify({"success": False, "message": "OTP expired"}), 400

    # OTP valid → delete it
    db.session.delete(record)
    db.session.commit()

    return jsonify({
        "success": True,
        "message": "OTP verified"
    }), 200

def reset_password():
    data = request.get_json()
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"success": False, "message": "Email and password required"}), 400

    user = User.query.filter_by(email=email).first()

    if not user or not user.must_reset_password:
        return jsonify({"success": False, "message": "Unauthorized request"}), 403

    hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
    user.password = hashed_pw
    user.must_reset_password = False
    user.status = "active"
    user.org_setup_completed = True

    db.session.commit()

    return jsonify({
        "success": True,
        "message": "Password reset successfully"
    }), 200

def logout():
    session.clear()
    return jsonify({'success': True, 'message': 'Logged out successfully'}), 200

@jwt_required()
def me():
    current_user = get_jwt_identity()
    return jsonify(logged_in_as=current_user), 200