"""Home-page data scoped to the signed-in user and organization."""
from datetime import datetime, timezone
from app.models import Agent, Dashboard, DataSourceConnection, FileMetadata, QueryLog


def home_overview(user):
    scope = {'user_id': user.id, 'organization_id': user.organization_id}
    agents = Agent.query.filter_by(**scope, is_deleted=False)
    dashboards = Dashboard.query.filter_by(**scope, is_active=True)
    connections = DataSourceConnection.query.filter_by(**scope, is_deleted=False)
    files = FileMetadata.query.filter_by(**scope, is_deleted=False)
    queries = QueryLog.query.filter_by(**scope)
    counts = {'files': files.count(), 'connections': connections.count(),
              'agents': agents.count(), 'dashboards': dashboards.count()}
    recent_dashboards = dashboards.order_by(Dashboard.updated_at.desc(), Dashboard.id.desc()).limit(6).all()
    steps = [
        {'title': 'Add your data', 'description': 'Upload a file or connect a database.',
         'url': '/data-management', 'done': counts['files'] + counts['connections'] > 0},
        {'title': 'Set up an AI agent', 'description': 'Choose which data your agent can answer questions about.',
         'url': '/agent-management', 'done': counts['agents'] > 0},
        {'title': 'Ask Copilot a question', 'description': 'Explore your data in plain language.',
         'url': '/copilot-page', 'done': queries.with_entities(QueryLog.id).first() is not None},
        {'title': 'Create a dashboard', 'description': 'Keep your useful charts together in one place.',
         'url': '/dashboard/builder', 'done': counts['dashboards'] > 0},
    ]
    activity = []
    for name, date in files.with_entities(FileMetadata.original_filename, FileMetadata.uploaded_at).order_by(FileMetadata.uploaded_at.desc()).limit(5):
        activity.append({'title': 'File uploaded', 'detail': name, 'date': date, 'url': '/data-management', 'icon': 'file-alt'})
    for name, date in agents.with_entities(Agent.name, Agent.created_at).order_by(Agent.created_at.desc()).limit(5):
        activity.append({'title': 'Agent created', 'detail': name, 'date': date, 'url': '/agent-management', 'icon': 'robot'})
    for item in recent_dashboards:
        activity.append({'title': 'Dashboard updated', 'detail': item.title, 'date': item.updated_at,
                         'url': f'/dashboard/view/{item.id}', 'icon': 'chart-bar'})
    # Avoid loading embeddings or sensitive question text for the activity feed.
    for (date,) in queries.with_entities(QueryLog.created_at).order_by(QueryLog.created_at.desc()).limit(5):
        activity.append({'title': 'Copilot question asked', 'detail': 'View your query history', 'date': date,
                         'url': '/query-log-analyzer', 'icon': 'comment-dots'})
    activity.sort(key=lambda item: item['date'] or datetime.min, reverse=True)
    return {'counts': counts, 'dashboards': recent_dashboards, 'activity': activity[:6],
            'steps': steps, 'completed': sum(step['done'] for step in steps),
            'next_step': next((step for step in steps if not step['done']), None),
            'updated_at': datetime.now(timezone.utc)}
