import os
import sys
import getpass
import re
from datetime import datetime

# Add the app directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from app.extensions import db, bcrypt
from app.models.user import User, Role

def validate_email(email):
    """Validate email format"""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_username(username):
    """Validate username format"""
    # Username should be 3-50 characters, alphanumeric and underscores only
    pattern = r'^[a-zA-Z0-9_]{3,50}$'
    return re.match(pattern, username) is not None

def validate_password(password):
    """Validate password strength"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r'\d', password):
        return False, "Password must contain at least one digit"
    
    return True, "Password is valid"

def get_user_input():
    """Get user input with validation"""
    print("=" * 50)
    print("CREATE SUPER ADMIN USER")
    print("=" * 50)
    
    # Get username
    while True:
        username = input("Enter username (3-50 characters, alphanumeric + underscore): ").strip()
        if not username:
            print("❌ Username cannot be empty!")
            continue
        
        if not validate_username(username):
            print("❌ Invalid username format! Use 3-50 characters, letters, numbers, and underscores only.")
            continue
        
        # Check if username already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            print(f"❌ Username '{username}' already exists!")
            continue
        
        break
    
    # Get email
    while True:
        email = input("Enter email address: ").strip()
        if not email:
            print("❌ Email cannot be empty!")
            continue
        
        if not validate_email(email):
            print("❌ Invalid email format!")
            continue
        
        # Check if email already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            print(f"❌ Email '{email}' already exists!")
            continue
        
        break
    
    # Get password
    while True:
        password = getpass.getpass("Enter password (hidden input): ")
        if not password:
            print("❌ Password cannot be empty!")
            continue
        
        is_valid, message = validate_password(password)
        if not is_valid:
            print(f"❌ {message}")
            continue
        
        # Confirm password
        confirm_password = getpass.getpass("Confirm password: ")
        if password != confirm_password:
            print("❌ Passwords do not match!")
            continue
        
        break
    
    # Get token quota (optional)
    while True:
        token_quota_input = input("Enter token quota (default: 1000000): ").strip()
        if not token_quota_input:
            token_quota = 1000000
            break
        
        try:
            token_quota = int(token_quota_input)
            if token_quota < 0:
                print("❌ Token quota must be a positive number!")
                continue
            break
        except ValueError:
            print("❌ Invalid number format!")
            continue
    
    return {
        'username': username,
        'email': email,
        'password': password,
        'token_quota': token_quota
    }

def create_roles_if_not_exist():
    """Create default roles if they don't exist"""
    roles_data = [
        {'name': 'superadmin', 'description': 'Super Administrator with full access'},
        {'name': 'admin', 'description': 'Administrator with limited access'},
        {'name': 'user', 'description': 'Regular user'},
        {'name': 'org_admin', 'description': 'Organization Administrator with limited access'},
        {'name': 'org_user', 'description': 'Organization User'}
    ]
    
    created_roles = []
    for role_data in roles_data:
        role = Role.query.filter_by(name=role_data['name']).first()
        if not role:
            role = Role(**role_data)
            db.session.add(role)
            created_roles.append(role_data['name'])
    
    if created_roles:
        db.session.commit()
        print(f"✅ Created roles: {', '.join(created_roles)}")
    
    return Role.query.filter_by(name='superadmin').first()

def create_superuser():
    """Main function to create superuser"""
    app = create_app()
    
    with app.app_context():
        print("🔄 Initializing database connection...")
        
        try:
            # Test database connection
            db.session.execute(db.text('SELECT 1'))

            print("✅ Database connection successful")
        except Exception as e:
            print(f"❌ Database connection failed: {e}")
            print("Make sure your database is running and configured correctly.")
            return False
        
        # Create roles if they don't exist
        print("🔄 Setting up roles...")
        superadmin_role = create_roles_if_not_exist()
        
        if not superadmin_role:
            print("❌ Failed to create or find superadmin role!")
            return False
        
        # Get user input
        user_data = get_user_input()
        
        # Confirm creation
        print("\n" + "=" * 50)
        print("CONFIRM SUPER ADMIN CREATION")
        print("=" * 50)
        print(f"Username: {user_data['username']}")
        print(f"Email: {user_data['email']}")
        print(f"Token Quota: {user_data['token_quota']:,}")
        print("Role: Super Admin")
        print("=" * 50)
        
        confirm = input("Create this super admin user? (y/N): ").strip().lower()
        if confirm not in ['y', 'yes']:
            print("❌ Super admin creation cancelled.")
            return False
        
        try:
            # Hash password
            print("🔄 Creating super admin user...")
            hashed_password = bcrypt.generate_password_hash(user_data['password']).decode('utf-8')
            
            # Create user
            superuser = User(
                username=user_data['username'],
                email=user_data['email'],
                password=hashed_password,
                token_quota=user_data['token_quota']
            )
            
            # Assign super admin role
            superuser.roles.append(superadmin_role)
            
            # Save to database
            db.session.add(superuser)
            db.session.commit()
            
            print("\n" + "🎉" * 20)
            print("✅ SUPER ADMIN USER CREATED SUCCESSFULLY!")
            print("🎉" * 20)
            print(f"Username: {user_data['username']}")
            print(f"Email: {user_data['email']}")
            print(f"Token Quota: {user_data['token_quota']:,}")
            print("Role: Super Admin")
            print("\n📝 Login credentials:")
            print(f"   Username: {user_data['username']}")
            print(f"   Password: [hidden for security]")
            print(f"\n🌐 Admin panel URL: http://localhost:5000/admin/login")
            print("\n⚠️  IMPORTANT: Please store these credentials securely!")
            
            return True
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Error creating super admin: {e}")
            return False

def list_existing_superusers():
    """List existing super admin users"""
    app = create_app()
    
    with app.app_context():
        try:
            superadmin_role = Role.query.filter_by(name='superadmin').first()
            if not superadmin_role:
                print("No super admin role found.")
                return
            
            superusers = User.query.filter(User.roles.contains(superadmin_role)).all()
            
            if not superusers:
                print("No super admin users found.")
                return
            
            print("\n" + "=" * 50)
            print("EXISTING SUPER ADMIN USERS")
            print("=" * 50)
            for user in superusers:
                status = "Active" if user.status == "active" else "Inactive"
                print(f"ID: {user.id} | Username: {user.username} | Email: {user.email} | Status: {status}")
            print("=" * 50)
            
        except Exception as e:
            print(f"❌ Error listing superusers: {e}")

def main():
    """Main menu function"""
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        if command == 'list':
            list_existing_superusers()
            return
        elif command == 'help':
            print_help()
            return
    
    print("🔧 Super Admin User Management")
    print("1. Create new super admin")
    print("2. List existing super admins")
    print("3. Exit")
    
    while True:
        try:
            choice = input("\nSelect an option (1-3): ").strip()
            
            if choice == '1':
                create_superuser()
                break
            elif choice == '2':
                list_existing_superusers()
                break
            elif choice == '3':
                print("👋 Goodbye!")
                break
            else:
                print("❌ Invalid choice. Please select 1, 2, or 3.")
                
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break
        except EOFError:
            print("\n\n👋 Goodbye!")
            break

def print_help():
    """Print help information"""
    print("""
Super Admin User Creation Script

Usage:
    python create_superuser.py          # Interactive mode
    python create_superuser.py list     # List existing super admins
    python create_superuser.py help     # Show this help

Password Requirements:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one digit

Username Requirements:
    - 3-50 characters
    - Letters, numbers, and underscores only
    - Must be unique

Email Requirements:
    - Valid email format
    - Must be unique
    """)

if __name__ == '__main__':
    main()
