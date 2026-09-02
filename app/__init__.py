from flask import Flask
import os
from dotenv import load_dotenv
from app.extensions import db, migrate, jwt, bcrypt, mail

load_dotenv()

template_dir = os.path.abspath("app/templates")


def create_app():
    app = Flask(__name__, template_folder=template_dir)
    app.config.from_object('app.config.Config')

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    bcrypt.init_app(app)

    app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtpout.secureserver.net')
    app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() in ('true', '1', 't')
    app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = (
        os.getenv('MAIL_DEFAULT_SENDER_NAME', 'Thinklee'),
        os.getenv('MAIL_DEFAULT_SENDER_EMAIL', 'amishra@cloudhubs.nl')
    )

    mail.init_app(app)

    from app.routes.auth_routes import auth_bp
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    from app.routes.page_routes import page_bp
    app.register_blueprint(page_bp)
    from app.routes.api_routes import data_bp, agent_bp, query_bp, dashboard_bp, profile_bp, org_bp
    app.register_blueprint(data_bp, url_prefix="/api/data")
    app.register_blueprint(agent_bp, url_prefix="/api/agent")
    app.register_blueprint(query_bp, url_prefix="/api/query")
    app.register_blueprint(dashboard_bp, url_prefix="/api/dashboard")
    app.register_blueprint(profile_bp, url_prefix="/api/profile")
    app.register_blueprint(org_bp, url_prefix="/api/org")
    
    from app.routes.admin_api_routes import admin_bp
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    
    from app.routes.admin_frontend_routes import admin_frontend_bp
    app.register_blueprint(admin_frontend_bp)

    return app
