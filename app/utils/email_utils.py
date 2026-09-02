import secrets
from flask_mail import Message
from app.extensions import mail

def send_invite_email(email, org_name, password, login_url, message):
    try:
        msg = Message(
            "You're invited to join " + org_name,
            recipients=[email]
        )
        msg.body = f"""
        Hi,

        You’ve been added to {org_name} to use Thinklee.

        {message}

        Your login credentials:

        Email: {email}
        Password: {password}

        Login here:
        {login_url}

        ⚠️ You’ll be required to change your password after first login.

        Thanks,
        Team Thinklee
        """
        mail.send(msg)

    except Exception as e:
        print(f"Error sending email: {str(e)}")



def generate_otp():
    return str(secrets.randbelow(10**6)).zfill(6)

