import re
from app.services.report_queries import execute_report_query, validate_sql
from app.utils.db_connections import normalize_config, resolve_engine
from app.utils.chart_data import chart_payload, CHART_TYPES
from app.models.agent import Agent
from app.models.dashboard import Dashboard, DashboardWidget
from flask import request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db


@jwt_required()
def create_dashboard():
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='A JSON object is required'), 400
        
        if data.get('description') is not None and not isinstance(data['description'], str):
            return jsonify(error='Description must be text'), 400
        # Validate required fields
        if not isinstance(data.get('title'), str) or not data['title'].strip() or len(data['title'].strip()) > 255:
            return jsonify({'error': 'Title is required'}), 400
        
        if not data.get('agent_id'):
            return jsonify({'error': 'Agent ID is required'}), 400
        
        # Verify agent exists and belongs to user
        agent = Agent.query.filter_by(id=data['agent_id'], user_id=current_user_id, is_deleted=False).first()
        if not agent:
            return jsonify({'error': 'Agent not found or unauthorized'}), 404

        # Create dashboard
        # organization_id is NOT NULL; take it from the agent so the dashboard
        # is tied to the same tenant as the data it reports on.
        dashboard = Dashboard(
            user_id=current_user_id,
            organization_id=agent.organization_id,
            agent_id=data['agent_id'],
            title=data['title'].strip(),
            description=data.get('description', '').strip() if data.get('description') else None
        )
        
        db.session.add(dashboard)
        db.session.commit()
        
        return jsonify({
            'message': 'Dashboard created successfully',
            'dashboard_id': dashboard.id,
            'dashboard': dashboard.to_dict()
        }), 201
        
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error creating dashboard: {str(e)}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        current_app.logger.error(f"Error creating dashboard: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@jwt_required()
def edit_dashboard(dashboard_id):
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='A JSON object is required'), 400

        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id, is_active=True).first()
        if not dashboard:
            return jsonify({'error': 'Dashboard not found or unauthorized'}), 404
        
        if not isinstance(data.get('title', dashboard.title), str) or not data.get('title', dashboard.title).strip() or len(data.get('title', dashboard.title).strip()) > 255:
            return jsonify(error='Title is required'), 400
        dashboard.title = data.get('title', dashboard.title).strip()
        if 'description' in data:
            if data['description'] is not None and not isinstance(data['description'], str):
                return jsonify(error='Description must be text'), 400
            dashboard.description = data['description'].strip() if data['description'] else None
        
        db.session.commit()
        
        return jsonify({
            'message': 'Dashboard updated successfully',
            'dashboard': dashboard.to_dict()
        }), 200
        
    except SQLAlchemyError as e:
        db.session.rollback()
        return jsonify(error='Unable to update dashboard'), 500

@jwt_required()
def create_widget(dashboard_id):
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='A JSON object is required'), 400
        
        # Validate dashboard ownership
        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id, is_active=True).first()
        if not dashboard:
            return jsonify({'error': 'Dashboard not found or unauthorized'}), 404
        
        # Validate required fields
        required_fields = ['widget_id', 'sql_query', 'chart_type']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
        try:
            validate_widget(data, dashboard.agent)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

        # Check if widget already exists (for updates)
        existing_widget = DashboardWidget.query.filter_by(
            dashboard_id=dashboard_id,
            widget_id=data['widget_id']
        ).first()
        
        if existing_widget:
            # Update existing widget
            widget = existing_widget
            widget.widget_name = data.get('widget_name', widget.widget_name)
            widget.nl_query = data.get('nl_query', widget.nl_query)
            widget.sql_query = data['sql_query']
            widget.chart_type = data['chart_type']
            widget.position = data.get('position', widget.position)
            widget.refresh_rate = data.get('refresh_rate', widget.refresh_rate)
            widget.chart_data = data.get('chart_data', widget.chart_data)
            widget.chart_config = data.get('chart_config', widget.chart_config)
            widget.is_active = data.get('is_active', widget.is_active)
            widget.order_index = data.get('order_index', widget.order_index)
            
            action = 'updated'
        else:
            # Create new widget
            widget = DashboardWidget(
                dashboard_id=dashboard_id,
                widget_id=data['widget_id'],
                widget_name=data.get('widget_name'),
                nl_query=data.get('nl_query'),
                sql_query=data['sql_query'],
                chart_type=data['chart_type'],
                position=data.get('position', {'x': 0, 'y': 0, 'w': 4, 'h': 8}),
                refresh_rate=data.get('refresh_rate', 'manual'),
                chart_data=data.get('chart_data'),
                chart_config=data.get('chart_config'),
                is_active=data.get('is_active', True),
                order_index=data.get('order_index', 0)
            )
            db.session.add(widget)
            action = 'created'
        
        db.session.commit()
        
        return jsonify({
            'message': f'Widget {action} successfully',
            'widget': widget.to_dict()
        }), 201 if action == 'created' else 200
        
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error creating/updating widget: {str(e)}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        current_app.logger.error(f"Error creating/updating widget: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

def validate_widget(data, agent):
    if not isinstance(data, dict):
        raise ValueError('Each widget must be an object.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,50}', str(data.get('widget_id', ''))):
        raise ValueError('Invalid widget identifier.')
    if data.get('chart_type') not in CHART_TYPES:
        raise ValueError('Unsupported chart type.')
    if not isinstance(data.get('sql_query'), str) or not data['sql_query'].strip():
        raise ValueError('Widget SQL is required.')
    dialect = resolve_engine(normalize_config(agent.data_connection)) if agent.data_connection_id else 'sqlite'
    validate_sql(data['sql_query'], dialect)
    if data.get('refresh_rate', 'manual') not in ('manual', 'daily', 'weekly', 'monthly'):
        raise ValueError('Invalid refresh rate.')


@jwt_required()
def bulk_save_widgets(dashboard_id):
    dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=get_jwt_identity(), is_active=True).first()
    if not dashboard:
        return jsonify(error='Dashboard not found'), 404
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('widgets'), list) or not 1 <= len(data['widgets']) <= 50:
        return jsonify(error='Provide between 1 and 50 widgets'), 400
    try:
        seen = set()
        for w in data['widgets']:
            validate_widget(w, dashboard.agent)
            if w['widget_id'] in seen:
                raise ValueError('Duplicate widget identifier.')
            seen.add(w['widget_id'])
        updated_ids = []
        for w in data['widgets']:
            widget = DashboardWidget.query.filter_by(dashboard_id=dashboard_id, widget_id=w['widget_id']).first()
            if not widget:
                widget = DashboardWidget(dashboard_id=dashboard_id, widget_id=w['widget_id'])
            for key in ('widget_name', 'nl_query', 'sql_query', 'chart_type', 'position'):
                setattr(widget, key, w.get(key))
            widget.refresh_rate = w.get('refresh_rate', 'manual')
            widget.chart_data = None  # Refresh from the authorized source, never trust client data.
            db.session.add(widget)
            db.session.flush()
            updated_ids.append(widget.id)
        db.session.commit()
        return jsonify(status='ok', updated_ids=updated_ids)
    except ValueError as exc:
        db.session.rollback()
        return jsonify(error=str(exc)), 400
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception('Widget save failed')
        return jsonify(error='Unable to save widgets'), 500

@jwt_required()
def delete_widget(dashboard_id, widget_id):
    """Delete a specific widget"""
    try:
        current_user_id = get_jwt_identity()
        
        # Validate dashboard ownership
        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id, is_active=True).first()
        if not dashboard:
            return jsonify({'error': 'Dashboard not found or unauthorized'}), 404
        
        # Find and delete widget
        widget = DashboardWidget.query.filter_by(
            dashboard_id=dashboard_id,
            widget_id=widget_id
        ).first()
        
        if not widget:
            return jsonify({'error': 'Widget not found'}), 404
        
        db.session.delete(widget)
        db.session.commit()
        
        return jsonify({'message': 'Widget deleted successfully'}), 200
        
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error deleting widget: {str(e)}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        current_app.logger.error(f"Error deleting widget: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@jwt_required()
def update_dashboard_layout(dashboard_id):
    """Update widget positions and dashboard layout"""
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='A JSON object is required'), 400
        
        # Validate dashboard ownership
        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id, is_active=True).first()
        if not dashboard:
            return jsonify({'error': 'Dashboard not found or unauthorized'}), 404
        
        layout_updates = data.get('layout', [])
        
        # Update widget positions
        for layout_item in layout_updates:
            widget_id = layout_item.get('id')
            position = {
                'x': layout_item.get('x', 0),
                'y': layout_item.get('y', 0),
                'w': layout_item.get('w', 4),
                'h': layout_item.get('h', 8)
            }
            
            widget = DashboardWidget.query.filter_by(
                dashboard_id=dashboard_id,
                widget_id=widget_id
            ).first()
            
            if widget:
                widget.position = position
        
        # Update dashboard layout config if provided
        if 'layout_config' in data:
            dashboard.layout_config = data['layout_config']
        
        db.session.commit()
        
        return jsonify({
            'message': 'Layout updated successfully',
            'dashboard': dashboard.to_dict()
        }), 200
        
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error updating layout: {str(e)}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        current_app.logger.error(f"Error updating layout: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@jwt_required()
def get_dashboard(dashboard_id):
    """Get dashboard with all widgets"""
    try:
        current_user_id = get_jwt_identity()
        
        dashboard = Dashboard.query.filter_by(
            id=dashboard_id, 
            user_id=current_user_id,
            is_active=True
        ).first()
        
        if not dashboard:
            return jsonify({'error': 'Dashboard not found or unauthorized'}), 404
        
        return jsonify({
            'dashboard': dashboard.to_dict()
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching dashboard: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@jwt_required()
def get_user_dashboards():
    """Get all dashboards for the current user"""
    try:
        current_user_id = get_jwt_identity()
        
        dashboards = Dashboard.query.filter_by(
            user_id=current_user_id,
            is_active=True
        ).order_by(Dashboard.updated_at.desc()).all()
        
        return jsonify({
            'dashboards': [d.to_dict() for d in dashboards]
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching user dashboards: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@jwt_required()
def update_dashboard(dashboard_id):
    """Update dashboard details"""
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(error='A JSON object is required'), 400
        
        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id, is_active=True).first()
        if not dashboard:
            return jsonify({'error': 'Dashboard not found or unauthorized'}), 404
        
        # Update allowed fields
        if 'title' in data:
            if not isinstance(data['title'], str) or not data['title'].strip() or len(data['title'].strip()) > 255:
                return jsonify(error='A title of 1 to 255 characters is required'), 400
            dashboard.title = data['title'].strip()
        if 'description' in data:
            if data['description'] is not None and not isinstance(data['description'], str):
                return jsonify(error='Description must be text'), 400
            dashboard.description = data['description'].strip() if data['description'] else None
        if 'is_active' in data:
            dashboard.is_active = data['is_active']
        
        db.session.commit()
        
        return jsonify({
            'message': 'Dashboard updated successfully',
            'dashboard': dashboard.to_dict()
        }), 200
        
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error updating dashboard: {str(e)}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        current_app.logger.error(f"Error updating dashboard: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@jwt_required()
def delete_dashboard(dashboard_id):
    """Delete a dashboard (soft delete)"""
    try:
        current_user_id = get_jwt_identity()
        
        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id, is_active=True).first()
        if not dashboard:
            return jsonify({'error': 'Dashboard not found or unauthorized'}), 404
        
        # Soft delete
        dashboard.is_active = False
        # Also soft delete all widgets
        for widget in dashboard.widgets:
            widget.is_active = False
        
        db.session.commit()
        
        return jsonify({'message': 'Dashboard deleted successfully'}), 200
        
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error deleting dashboard: {str(e)}")
        return jsonify({'error': 'Database error occurred'}), 500
    except Exception as e:
        current_app.logger.error(f"Error deleting dashboard: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@jwt_required()
def get_widget_data(widget_id):
    """Re-run a saved widget's query.

    Previously unauthenticated and unscoped: any caller could read any
    widget's data, and the stored SQL was executed without checking who owned
    it.
    """
    current_user_id = get_jwt_identity()

    widget = (
        DashboardWidget.query
        .join(Dashboard, Dashboard.id == DashboardWidget.dashboard_id)
        .filter(
            DashboardWidget.id == widget_id,
            Dashboard.user_id == current_user_id
        )
        .first()
    )

    if not widget:
        return jsonify({"error": "Widget not found"}), 404

    try:
        dashboard = Dashboard.query.filter_by(id=widget.dashboard_id, user_id=current_user_id, is_active=True).first()
        if not dashboard or not widget.is_active:
            return jsonify(error='Widget not found'), 404
        agent = Agent.query.filter_by(id=dashboard.agent_id, user_id=current_user_id, is_deleted=False).first()
        if not agent:
            return jsonify(error='Agent not found'), 404
        rows = execute_report_query(agent, widget.sql_query)
        payload = chart_payload(rows, widget.chart_type)
        return jsonify(dict(payload, widget_id=widget.id, widget_name=widget.widget_name))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    except Exception as e:
        current_app.logger.error(f"Error running widget {widget_id}: {e}")
        return jsonify({"error": "Failed to run widget query"}), 500


@jwt_required()
def list_widgets(dashboard_id):
    """List a dashboard's widgets, scoped to the requesting user."""
    current_user_id = get_jwt_identity()

    dashboard = Dashboard.query.filter_by(
        id=dashboard_id,
        user_id=current_user_id
    ).first()

    if not dashboard:
        return jsonify({"error": "Dashboard not found"}), 404

    return jsonify({"widgets": [w.to_dict() for w in dashboard.widgets]})
