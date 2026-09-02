from app.extensions import db

class UploadedFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False
    )
    table_metadata_id = db.Column(db.Integer, db.ForeignKey("table_metadata.id"), nullable=True)
    original_filename = db.Column(db.String(255), nullable=False)
    table_name = db.Column(db.String(255), nullable=False)
    upload_time = db.Column(db.DateTime, server_default=db.func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "original_filename": self.original_filename,
            "table_name": self.table_name,
            "upload_time": self.upload_time
        }

    def __repr__(self):
        return f"UploadedFile(id={self.id}, user_id={self.user_id}, original_filename={self.original_filename}, table_name={self.table_name}, upload_time={self.upload_time})"