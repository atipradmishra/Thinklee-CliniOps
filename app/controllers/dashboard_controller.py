from app.models.agent import Agent
from app.models.dashboard import Dashboard, DashboardWidget
from app.services.query_sql_agent import execute_sql_query
from flask import request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from sqlalchemy.exc import SQLAlchemyError
from app.extensions import db


@jwt_required()
def create_dashboard():
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        # Validate required fields
        if not data.get('title'):
            return jsonify({'error': 'Title is required'}), 400
        
        if not data.get('agent_id'):
            return jsonify({'error': 'Agent ID is required'}), 400
        
        # Verify agent exists and belongs to user
        agent = Agent.query.filter_by(id=data['agent_id'], user_id=current_user_id).first()
        if not agent:
            return jsonify({'error': 'Agent not found or unauthorized'}), 404
        
        # Create dashboard
        dashboard = Dashboard(
            user_id=current_user_id,
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
        data = request.get_json()

        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id).first()
        if not dashboard:
            return jsonify({'error': 'Dashboard not found or unauthorized'}), 404
        
        dashboard.title = data.get('title', dashboard.title).strip()
        dashboard.description = data.get('description', dashboard.description).strip() if data.get('description') else None
        
        db.session.commit()
        
        return jsonify({
            'message': 'Dashboard updated successfully',
            'dashboard': dashboard.to_dict()
        }), 200
        
    except SQLAlchemyError as e:
        db.session.rollback()

@jwt_required()
def create_widget(dashboard_id):
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        
        # Validate dashboard ownership
        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id).first()
        if not dashboard:
            return jsonify({'error': 'Dashboard not found or unauthorized'}), 404
        
        # Validate required fields
        required_fields = ['widget_id', 'sql_query', 'chart_type']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'{field} is required'}), 400
        
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

@jwt_required()
def bulk_save_widgets(dashboard_id):
    data = request.get_json() or {}
    widgets = data.get('widgets', [])

    updated_ids = []
    for w in widgets:
        db_id = w.get('id')
        if db_id:
            widget = DashboardWidget.query.filter_by(id=db_id, dashboard_id=dashboard_id).first_or_404()
        else:
            existing = DashboardWidget.query.filter_by(dashboard_id=dashboard_id, widget_id=w.get('widget_id')).first()
            widget = existing or DashboardWidget(dashboard_id=dashboard_id, widget_id=w.get('widget_id'))

        widget.widget_name = w.get('widget_name') or 'Untitled Widget'
        widget.chart_type  = w.get('chart_type') or 'bar'
        widget.refresh_rate = w.get('refresh_rate')
        widget.nl_query    = w.get('nl_query')
        widget.sql_query   = w.get('sql_query')
        widget.position = (w.get('position') or {})
        widget.chart_data = w.get('chart_data')

        db.session.add(widget)
        db.session.flush()
        updated_ids.append(widget.id)

    db.session.commit()
    return jsonify({"status": "ok", "updated_ids": updated_ids})

@jwt_required()
def delete_widget(dashboard_id, widget_id):
    """Delete a specific widget"""
    try:
        current_user_id = get_jwt_identity()
        
        # Validate dashboard ownership
        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id).first()
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
        data = request.get_json()
        
        # Validate dashboard ownership
        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id).first()
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
        data = request.get_json()
        
        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id).first()
        if not dashboard:
            return jsonify({'error': 'Dashboard not found or unauthorized'}), 404
        
        # Update allowed fields
        if 'title' in data:
            dashboard.title = data['title'].strip()
        if 'description' in data:
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
        
        dashboard = Dashboard.query.filter_by(id=dashboard_id, user_id=current_user_id).first()
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

def get_widget_data(widget_id):
    widget = DashboardWidget.query.get_or_404(widget_id)
    try:
        result = db.session.execute(widget.sql_query)
        columns = result.keys()
        rows = [dict(zip(columns, row)) for row in result.fetchall()]
        
        return jsonify({
            "widget_id": widget.id,
            "title": widget.title,
            "chart_type": widget.chart_type,
            "data": rows
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
def list_widgets(dashboard_id):
    dashboard = Dashboard.query.get_or_404(dashboard_id)
    widgets = [w.to_dict() for w in dashboard.widgets]
    return jsonify({"widgets": widgets})
