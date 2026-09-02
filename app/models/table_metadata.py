from app.extensions import db

class TableMetadata(db.Model):
    __tablename__ = 'table_of_uploadedfiles_metadata'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False
    )
    table_name = db.Column(db.String(255), nullable=False)
    schema = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    agentmap = db.relationship("AgentTableMap", back_populates="table")
    files = db.relationship("FileMetadata", back_populates="table")
    user = db.relationship("User", back_populates="tables")
    organization = db.relationship("Organization", back_populates="tables")

    is_deleted = db.Column(db.Boolean, server_default=db.false(), nullable=False)

    def delete(self):
        self.is_deleted = True
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "table_name": self.table_name,
            "schema": self.schema,
            "created_at": self.created_at
        }