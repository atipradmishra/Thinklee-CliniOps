from app.extensions import db

class Organization(db.Model):
    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    plan = db.Column(db.String(50), server_default="free")
    time_zone = db.Column(db.String(50), nullable=True)
    industry = db.Column(db.String(50), nullable=True)
    team_size = db.Column(db.String(50), nullable=True)
    is_active = db.Column(db.Boolean, server_default=db.true())
    created_at = db.Column(db.DateTime, server_default=db.func.now())

    users = db.relationship("User", back_populates="organization")
    data_connections = db.relationship("DataSourceConnection", back_populates="organization")
    tables = db.relationship("TableMetadata", back_populates="organization")
    dashboards = db.relationship(
        "Dashboard",
        back_populates="organization",
        cascade="all, delete-orphan"
    )
    agents = db.relationship("Agent", back_populates="organization")

    members = db.relationship(
        "OrganizationMember",
        back_populates="organization",
        cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Organization {self.name}>"

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "plan": self.plan,
            "is_active": self.is_active
        }
    

class OrganizationMember(db.Model):
    __tablename__ = "organization_members"

    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(
        db.Integer, db.ForeignKey("organizations.id"), nullable=False
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False
    )

    employee_id = db.Column(db.Integer, nullable=True)
    job_title = db.Column(db.String(50), nullable=True)

    role = db.Column(
        db.String(50),
        nullable=False,
        default="org_user"
    )  # org_admin | org_user

    user = db.relationship("User", back_populates="org_memberships")
    organization = db.relationship("Organization", back_populates="members")

    joined_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("organization_id", "user_id"),
    )
