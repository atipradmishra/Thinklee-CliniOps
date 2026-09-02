import base64
from app.extensions import db

class DataSourceConnection(db.Model):
    __tablename__ = 'data_source_connections'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False
    )
    source_name = db.Column(db.String(100), nullable=False)
    source_type = db.Column(db.String(50), nullable=False)

    # Common fields
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    connection_status = db.Column(db.String(20), default="Unknown")

    # Authentication (for RDBMS, Snowflake)
    username = db.Column(db.String(100))
    password = db.Column(db.String(100))

    # Relational DB fields
    host = db.Column(db.String(255))
    port = db.Column(db.String(10))
    server = db.Column(db.String(255))
    database = db.Column(db.String(255))
    driver = db.Column(db.String(100))

    # Managed relational services (source_type "rds" / "azure_sql") reuse the
    # fields above; this records which engine an RDS instance actually runs.
    rds_engine = db.Column(db.String(20))

    # Snowflake-specific
    snowflake_account = db.Column(db.String(255))
    snowflake_warehouse = db.Column(db.String(255))
    snowflake_schema = db.Column(db.String(255))

    # S3-specific
    s3_access_key = db.Column(db.String(255))
    s3_secret_key = db.Column(db.String(255))
    s3_region = db.Column(db.String(100))
    s3_bucket = db.Column(db.String(255))
    s3_prefix = db.Column(db.String(255))

    # SQLite-specific
    sqlite_path = db.Column(db.String(255))

    agents = db.relationship('Agent', back_populates='data_connection')
    organization = db.relationship("Organization", back_populates="data_connections")

    is_deleted = db.Column(db.Boolean, default=False)

    @classmethod
    def query_non_deleted(cls):
        return cls.query.filter_by(is_deleted=False)

    def delete(self):
        self.is_deleted = True
        db.session.commit()

    def to_dict(self):
        def decode_field(value):
            return base64.b64decode(value.encode()).decode() if value else None
        
        return {
            "id": self.id,
            "user_id": self.user_id,
            "source_name": self.source_name,
            "source_type": self.source_type,
            "username": self.username,
            "password": decode_field(self.password),
            "host": self.host,
            "port": self.port,
            "server": self.server,
            "database": self.database,
            "driver": self.driver,
            "rds_engine": self.rds_engine,
            "snowflake_account": self.snowflake_account,
            "snowflake_warehouse": self.snowflake_warehouse,
            "snowflake_schema": self.snowflake_schema,
            "s3_access_key": self.s3_access_key,
            "s3_secret_key": decode_field(self.s3_secret_key),
            "s3_region": self.s3_region,
            "s3_bucket": self.s3_bucket,
            "s3_prefix": self.s3_prefix,
            "sqlite_path": self.sqlite_path,
            "created_at": self.created_at,
            "connection_status": self.connection_status
        }

    def __repr__(self):
        return f"<DataConnection {self.source_name}>"
