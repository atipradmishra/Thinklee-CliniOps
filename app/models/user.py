from app.extensions import db

user_roles = db.Table(
    'user_roles',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id')),
    db.Column('role_id', db.Integer, db.ForeignKey('role.id'))
)

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))

    def __repr__(self):
        return f"<Role {self.name}>"

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    first_name = db.Column(db.String(30), nullable=True)
    last_name = db.Column(db.String(30), nullable=True)
    profile_pic_url = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    contact_number = db.Column(db.String(20), nullable=True)
    password = db.Column(db.String(128), nullable=False)
    must_reset_password = db.Column(
        db.Boolean,
        default=True,
        nullable=False,
        server_default=db.true()
    )
    trial_expires_at = db.Column(db.DateTime, nullable=True)
    token_quota = db.Column(db.Integer, nullable=False, default=100000)
    tokens_used_today = db.Column(db.Integer, nullable=False, default=0)
    # is_active = db.Column(db.Boolean, nullable=False, default=True)
    status = db.Column(db.String(20), nullable=False, default="active")
    last_login = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=db.func.current_timestamp())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    # Relations
    roles = db.relationship('Role', secondary=user_roles, backref=db.backref('users', lazy='dynamic'))
    agents = db.relationship('Agent', back_populates='user')
    dashboards = db.relationship("Dashboard", back_populates="user", cascade="all, delete-orphan")
    tables = db.relationship("TableMetadata", back_populates="user")

    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=True
    )

    organization = db.relationship("Organization", back_populates="users")
    org_setup_completed = db.Column(
        db.Boolean,
        default=False,
        nullable=False,
        server_default=db.false()
    )

    # NULL until the user finishes or dismisses the product tour. Stored per
    # user rather than in localStorage so "first login" survives a new browser.
    tour_completed_at = db.Column(db.DateTime, nullable=True)
    org_memberships = db.relationship(
        "OrganizationMember",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    def has_role(self, role_name):
        return any(role.name == role_name for role in self.roles)

    def is_super_admin(self):
        return self.has_role('superadmin')

    def to_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone": self.contact_number,
            "avatar_url": self.profile_pic_url,

            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,

            "trial_expires_at": self.trial_expires_at.isoformat() if self.trial_expires_at else None,
            "token_quota": self.token_quota,
            "tokens_used_today": self.tokens_used_today,

            # Stats (used in profile UI)
            "stats": {
                "dashboards": len(self.dashboards),
                "logins": self.tokens_used_today
            },

            # Org
            "organization_id": self.organization_id,
            "org_setup_completed": self.org_setup_completed,
            "tour_completed": self.tour_completed_at is not None,
            "tour_completed_at": self.tour_completed_at.isoformat() if self.tour_completed_at else None,

            # Roles
            "roles": [role.name for role in self.roles]
        }

    def __repr__(self):
        return f"<User {self.username}>"

class EmailOTP(db.Model):
    __tablename__ = 'email_otps'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False)
    otp = db.Column(db.String(6), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
