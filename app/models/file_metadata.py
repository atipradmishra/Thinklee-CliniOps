from app.extensions import db

class FileMetadata(db.Model):
    __tablename__ = 'file_metadata'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False
    )
    table_metadata_id = db.Column(db.Integer, db.ForeignKey("table_of_uploadedfiles_metadata.id"), nullable=True)
    original_filename = db.Column(db.String(255), nullable=False, default="unknown")
    file_size = db.Column(db.String(10), nullable=True)
    language = db.Column(db.String(10), nullable=True)
    uploaded_at = db.Column(db.DateTime, server_default=db.func.now())

    table = db.relationship("TableMetadata", back_populates="files")
    chunks = db.relationship("Chunk", back_populates="file_metadata")
    agents = db.relationship("AgentFileMap", back_populates="file")

    is_deleted = db.Column(db.Boolean, server_default=db.false(), nullable=False)

    def delete(self):
        self.is_deleted = True

        for chunk in self.chunks:
            chunk.delete()

        if self.table:
            self.table.delete()

        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "organization_id": self.organization_id,
            "original_filename": self.original_filename,
            "table_metadata_id": self.table_metadata_id,
            "file_size": self.file_size,
            "table_name": self.table.table_name if self.table else None,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None
        }
