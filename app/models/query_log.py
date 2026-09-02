from app.extensions import db

class QueryLog(db.Model):
    __tablename__ = 'query_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False
    )
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), nullable=False)

    user_query = db.Column(db.Text, nullable=False)
    user_query_embedding = db.Column(db.PickleType)
    generated_sql = db.Column(db.Text)
    ai_response = db.Column(db.Text)
    response_embedding = db.Column(db.PickleType)
    source_type = db.Column(db.String(20), nullable=True)
    feedback_rating = db.Column(db.String(10), nullable=True, default="neutral")
    issues = db.Column(db.JSON, default=[])  
    feedback_comment = db.Column(db.Text, nullable=True)
    feedback_embedding = db.Column(db.PickleType, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    agent = db.relationship("Agent", back_populates="query_log")

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'agent_id': self.agent_id,
            'agent_name': self.agent.name,
            'user_query': self.user_query,
            'generated_sql': self.generated_sql,
            'ai_response': self.ai_response,
            'source_type': self.source_type,
            'feedback_rating': self.feedback_rating,
            'issues': self.issues,
            'feedback_comment': self.feedback_comment,
            "created_at": self.created_at.isoformat()
        }
