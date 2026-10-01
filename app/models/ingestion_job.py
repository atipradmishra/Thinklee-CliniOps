from app.extensions import db

# Lifecycle:
#
#   queued ──► running ──┬─► succeeded     every file ingested
#                        ├─► partial       some files failed
#                        ├─► failed        nothing ingested
#                        └─► interrupted   process died mid-run; set on boot
STATUSES = ("queued", "running", "succeeded", "partial", "failed", "interrupted")
TERMINAL = ("succeeded", "partial", "failed", "interrupted")


class IngestionJob(db.Model):
    """One background document-ingestion run.

    Document ingestion embeds every chunk of every file, which takes roughly
    1.1 s per 1000-character chunk on CPU — minutes for a single large PDF.
    That cannot be done inside a request, so the upload endpoint stages the
    files, creates one of these, and returns immediately.
    """

    __tablename__ = "ingestion_jobs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True
    )

    status = db.Column(db.String(20), nullable=False, default="queued", index=True)
    file_category = db.Column(db.String(20), nullable=False, default="unstructured")

    total_files = db.Column(db.Integer, nullable=False, default=0)
    processed_files = db.Column(db.Integer, nullable=False, default=0)
    succeeded_files = db.Column(db.Integer, nullable=False, default=0)
    failed_files = db.Column(db.Integer, nullable=False, default=0)

    # Per-file outcome: [{filename, success, message, chunks}]
    results = db.Column(db.JSON, nullable=False, default=list)
    # Set only when the job itself fails, as opposed to an individual file.
    error = db.Column(db.Text, nullable=True)

    # Where the uploaded bytes were staged. Removed when the job finishes.
    staging_dir = db.Column(db.String(512), nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now(), index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    @property
    def is_terminal(self):
        return self.status in TERMINAL

    @property
    def percent(self):
        if not self.total_files:
            return 0
        return round(self.processed_files / self.total_files * 100)

    def to_dict(self):
        return {
            "id": self.id,
            "status": self.status,
            "file_category": self.file_category,
            "total_files": self.total_files,
            "processed_files": self.processed_files,
            "succeeded_files": self.succeeded_files,
            "failed_files": self.failed_files,
            "percent": self.percent,
            "results": self.results or [],
            "error": self.error,
            "is_terminal": self.is_terminal,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }

    def __repr__(self):
        return f"<IngestionJob {self.id} {self.status} {self.processed_files}/{self.total_files}>"
