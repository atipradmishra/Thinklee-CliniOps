from app.extensions import db

class Dashboard(db.Model):
    __tablename__ = "dashboard"

    id = db.Column(db.Integer, primary_key=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False
    )
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    layout_config = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    user = db.relationship("User", back_populates="dashboards")
    organization = db.relationship(
        "Organization",
        back_populates="dashboards"
    )
    agent = db.relationship("Agent", back_populates="dashboards")
    widgets = db.relationship(
            "DashboardWidget",
            back_populates="dashboard",
            cascade="all, delete-orphan",
            passive_deletes=True
        )

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'agent_id': self.agent_id,
            'title': self.title,
            'description': self.description,
            'is_active': self.is_active,
            'layout_config': self.layout_config,
            'widget_count': len(self.widgets),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'widgets': [widget.to_dict() for widget in self.widgets]
        }

class DashboardWidget(db.Model):
    __tablename__ = "dashboard_widget"

    id = db.Column(db.Integer, primary_key=True, index=True)
    dashboard_id = db.Column(db.Integer, db.ForeignKey("dashboard.id"), nullable=False)
    widget_id = db.Column(db.String(50), nullable=False)  # Frontend widget ID (e.g., "widget-123456")
    widget_name = db.Column(db.String(255), nullable=True)
    nl_query = db.Column(db.Text, nullable=True)
    sql_query = db.Column(db.Text, nullable=False)
    chart_type = db.Column(db.String(50), nullable=False)  # "bar", "line", "pie", "table", "summary"
    position = db.Column(db.JSON, nullable=True)  # { x: 0, y: 0, w: 4, h: 2 }
    refresh_rate = db.Column(db.String(20), nullable=True, default="manual")  # "manual", "daily", "weekly", "monthly"
    chart_data = db.Column(db.JSON, nullable=True)  # Store chart data for caching
    chart_config = db.Column(db.JSON, nullable=True)  # Store chart configuration
    is_active = db.Column(db.Boolean, default=True)
    order_index = db.Column(db.Integer, default=0)  # For widget ordering
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    dashboard = db.relationship("Dashboard", back_populates="widgets")

    def to_dict(self):
        return {
            'id': self.id,
            'dashboard_id': self.dashboard_id,
            'widget_id': self.widget_id,
            'widget_name': self.widget_name,
            'nl_query': self.nl_query,
            'sql_query': self.sql_query,
            'chart_type': self.chart_type,
            'position': self.position,
            'refresh_rate': self.refresh_rate,
            'chart_data': self.chart_data,
            'chart_config': self.chart_config,
            'is_active': self.is_active,
            'order_index': self.order_index,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
