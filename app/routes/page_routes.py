from app.models.dashboard import Dashboard
from app.models.organization import Organization
from app.models.user import User
from app.utils.auth_guards import (
    login_required,
    login_required_no_setup,
    redirect_if_authenticated,
    session_user,
)
from app.utils.decorators import roles_required
from flask import Blueprint, abort, render_template, redirect, url_for, session
from flask import send_from_directory

page_bp = Blueprint("page_bp", __name__)

@page_bp.route("/")
@redirect_if_authenticated
def index():
    """Marketing landing page. Signed-in users go straight to the app."""
    return render_template("landing.html")

@page_bp.route('/auth')
@redirect_if_authenticated
def auth_page():
    """Sign in / sign up. Signed-in users are bounced to their landing page."""
    return render_template('auth.html')

@page_bp.route('/reset-password')
def reset_password():
    return render_template('reset_password.html')

@page_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('page_bp.auth_page'))

@page_bp.route('/steps')
@login_required
def steps_page():
    return render_template('steps.html')

@page_bp.route('/org-setup')
@login_required_no_setup
def org_setup_page():
    """Reached straight after first login, before an organization exists."""
    return render_template('org_setup.html')

@page_bp.route("/data-management")
@login_required
def data_management():
    return render_template("data_management.html", token=session.get('access_token'))

@page_bp.route('/home')
@login_required
def home():
    user = session_user()

    stats = {
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

@page_bp.route('/agent-management')
@login_required
def rag_configure():
    return render_template("agent_management.html")

@page_bp.route("/copilot-page")
@login_required
def chat_with_rag():
    return render_template("copilot.html")

@page_bp.route("/graph-query")
@login_required
def graph_query():
    return render_template("graph_query.html")

@page_bp.route("/query-log-analyzer")
@login_required
def query_log():
    return render_template("query_log_analyzer.html")

@page_bp.route("/dashboard-config")
@login_required
def dashboard_config():
    return render_template("dashboard_management.html")

@page_bp.route("/dashboard/builder")
@login_required
def add_dashboard():
    return render_template("dashboard_setup.html")

def _owned_dashboard(dashboard_id, user):
    """Fetch a dashboard belonging to this user, or 404.

    Without the ownership filter any signed-in user could read another
    account's dashboard by changing the id in the URL. Scoped by user_id to
    match how the dashboard API already filters.
    """
    dashboard = Dashboard.query.filter_by(
        id=dashboard_id,
        user_id=user.id
    ).first()

    if not dashboard:
        abort(404)

    return dashboard

@page_bp.route("/dashboard/build/<int:dashboard_id>")
@login_required
def add_widget(dashboard_id):
    dashboard = _owned_dashboard(dashboard_id, session_user())
    return render_template("add_widgets.html", dashboard=dashboard)

@page_bp.route('/dashboard/view/<int:dashboard_id>')
@login_required
def view_dashboard(dashboard_id):
    dashboard = _owned_dashboard(dashboard_id, session_user())
    return render_template('dashboard_view.html', dashboard=dashboard)

@page_bp.route('/download-template')
@login_required
def download_template():
    return send_from_directory(directory='static/templates', path='template_metadata.xlsx', as_attachment=True)

@page_bp.route('/download-business-glossary-template')
@login_required
def download_business_glossary_template():
    return send_from_directory(directory='static/templates', path='template_glossary.csv', as_attachment=True)

@page_bp.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=session_user())

@page_bp.route('/org-users')
@login_required
@roles_required("org_admin", "super_admin")
def org_users():
    user = session_user()
    org = Organization.query.filter_by(id=user.organization_id).first()
    return render_template('org_users.html', org=org)
