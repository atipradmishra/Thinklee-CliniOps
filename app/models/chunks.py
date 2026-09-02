from app.extensions import db

class Chunk(db.Model):
    __tablename__ = "file_chunks"

    id = db.Column(db.Integer, primary_key=True)
    file_metadata_id = db.Column(db.Integer, db.ForeignKey("file_metadata.id"), nullable=False)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), nullable=True)

    chunk_index = db.Column(db.Integer, nullable=False)
    text = db.Column(db.Text, nullable=False)
    embedding_json = db.Column(db.JSON, nullable=False)

    file_metadata = db.relationship("FileMetadata", back_populates="chunks")
    agent = db.relationship("Agent", back_populates="chunks")

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    is_deleted = db.Column(db.Boolean, default=False)

    def delete(self):
        self.is_deleted = True
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "file_metadata_id": self.file_metadata_id,
            "agent_id": self.agent_id,
            "chunk_index": self.chunk_index,
            "text": self.text,
            "embedding": self.embedding_json,
            "created_at": self.created_at
        }

    def __repr__(self):
        return f"<Chunk file={self.file_metadata_id} idx={self.chunk_index}>"
