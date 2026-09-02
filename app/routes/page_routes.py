from datetime import datetime
from app.models.dashboard import Dashboard
from app.models.organization import Organization
from app.models.user import User
from app.utils.decorators import roles_required
from flask import Blueprint, render_template, redirect, url_for, session
from flask_jwt_extended import decode_token
from flask import send_from_directory
from jwt import ExpiredSignatureError, InvalidTokenError

page_bp = Blueprint("page_bp", __name__)

@page_bp.route("/")
def index():
    return render_template("landing.html")

@page_bp.route('/auth')
def auth_page():
    return render_template('auth.html')

@page_bp.route('/reset-password')
def reset_password():
    return render_template('reset_password.html')

@page_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('page_bp.auth_page'))

@page_bp.route('/steps')
def steps_page():
    return render_template('steps.html')

@page_bp.route('/org-setup')
def org_setup_page():
    return render_template('org_setup.html')

@page_bp.route("/data-management")
def data_management():
    token = session.get('access_token')
    if not token:
        return redirect(url_for('page_bp.auth_page'))
    return render_template("data_management.html", token=token)

@page_bp.route("/add-datasource")
def add_datasource():
    return render_template("add_datasource.html") 

@page_bp.route('/home')
def home():
    token = session.get('access_token')
    if not token:
        return redirect(url_for('page_bp.login_page'))

    try:
        decoded = decode_token(token)
        user_id = decoded.get('sub')
        user = User.query.get(user_id)

        if not user:
            return redirect(url_for('page_bp.login_page'))
        
        stats =  {
            'dashboards': '',
            'widgets': '',
            'connections': '',
            'activeUsers': '',
            'dataProcessed': '',
            'queriesToday': ''
        }

        # First visit to /home after signing up: run the product tour.
        show_tour = user.tour_completed_at is None

        return render_template(
            'home.html',
            user=user,
            stats=stats,
            show_tour=show_tour
        )

    except ExpiredSignatureError:
        return redirect(url_for('page_bp.login_page'))

    except InvalidTokenError:
        return redirect(url_for('page_bp.auth_page'))

    except Exception as e:
        print(f"Unexpected error in /home: {e}")
        return redirect(url_for('page_bp.auth_page'))

@page_bp.route('/agent-management')
def rag_configure():
    return render_template("agent_management.html")

@page_bp.route('/add-agent')
def add_agent():
    return render_template("rag_configure.html") 

@page_bp.route("/copilot-page")
def chat_with_rag():
    return render_template("copilot.html")

@page_bp.route("/graph-query")
def graph_query():
    return render_template("graph_query.html")

@page_bp.route("/query-log-analyzer")
def query_log():
    return render_template("query_log_analyzer.html")

@page_bp.route("/dashboard-config")
def dashboard_config():
    return render_template("dashboard_management.html")

@page_bp.route("/dashboard/builder")
def add_dashboard():
    return render_template("dashboard_setup.html")
    # return render_template("add_dashboard_working.html")

@page_bp.route("/dashboard/build/<int:dashboard_id>")
def add_widget(dashboard_id):
    dashboard = Dashboard.query.get(dashboard_id)
    return render_template("add_widgets.html", dashboard=dashboard)

@page_bp.route('/dashboard/view/<int:dashboard_id>')
def view_dashboard(dashboard_id):
    dashboard = Dashboard.query.get(dashboard_id)
    return render_template('dashboard_view.html', dashboard=dashboard)

@page_bp.route('/download-template')
def download_template():
    return send_from_directory(directory='static/templates', path='template_metadata.xlsx', as_attachment=True)

# @page_bp.route('/business_glossary')
# def business_glossary():
#     return render_template('business_glossary.html')

@page_bp.route('/download-business-glossary-template')
def download_business_glossary_template():
    return send_from_directory(directory='static/templates', path='template_glossary.csv', as_attachment=True)

# @page_bp.route('/user-list')
# def user_list():
#     return render_template('user_list.html')

@page_bp.route('/api/progress-data')
def steps_api_data():
    return {
        "user": {
            "name": "John Doe",
            "email": "john@example.com",
            "status": "active"
        },
        "progress": {
            "percentage": 40,
            "completed_steps": 2,
            "in_progress_steps": 1,
            "remaining_steps": 3
        },
        "steps": [
            {
                "id": 1,
                "title": "Connect Data Source",
                "description": "Successfully connect to Snowflake, AWS RDS, Azure SQL, or upload Excel/CSV files.",
                "status": "completed",
                "icon": "fas fa-database",
                "action_text": "Manage",
                "action_url": "/data-management"
            },
            {
                "id": 2,
                "title": "Create AI Agent",
                "description": "Define an intelligent AI agent that understands your data and can provide contextual insights.",
                "status": "completed",
                "icon": "fas fa-robot",
                "action_text": "Edit",
                "action_url": "/agent-management"
            },
            {
                "id": 3,
                "title": "Set Prompt Templates",
                "description": "Configure how your AI responds using customized prompt templates for consistent results.",
                "status": "current",
                "icon": "fas fa-comments",
                "action_text": "Configure",
                "action_url": "/agent-management"
            },
            {
                "id": 4,
                "title": "Run NL Queries",
                "description": "Ask questions in plain English and receive powerful visual insights powered by NLP.",
                "status": "pending",
                "icon": "fas fa-search",
                "action_text": "Locked",
                "action_url": "#"
            },
            {
                "id": 5,
                "title": "Run Graph Queries",
                "description": "Ask questions in plain English and visualize insights in interactive graphs and charts.",
                "status": "pending",
                "icon": "fas fa-chart-line",
                "action_text": "Locked",
                "action_url": "#"
            },
            {
                "id": 6,
                "title": "Configure Dashboard",
                "description": "Create and configure interactive dashboards with customizable widgets powered by your AI agents.",
                "status": "pending",
                "icon": "fas fa-tachometer-alt",
                "action_text": "Locked",
                "action_url": "#"
            }
        ],
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

@page_bp.route('/profile')
def profile():
    user = User.query.filter_by(id=session.get('id')).first()
    return render_template('profile.html', user=user)

@page_bp.route('/org-users')
@roles_required("org_admin", "super_admin")
def org_users():
    user = User.query.filter_by(id=session.get('id')).first()
    org_id = user.organization_id
    org = Organization.query.filter_by(id=org_id).first()
    return render_template('org_users.html', org=org)
