from app.extensions import db

class Agent(db.Model):
    __tablename__ = "agents"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    organization_id = db.Column(
        db.Integer,
        db.ForeignKey("organizations.id"),
        nullable=False
    )
    user = db.relationship('User', back_populates='agents')
    organization = db.relationship('Organization', back_populates='agents')
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    llm_provider = db.Column(db.String(50), nullable=False, default="openai")
    llm_model = db.Column(db.String(20), nullable=False,default="gpt-4")
    temperature = db.Column(db.Float, nullable=False, default=0.7)
    max_tokens = db.Column(db.Integer, nullable=True, default=1000)
    status = db.Column(db.String(20), nullable=False, default="active")

    sql_system_prompt = db.Column(db.Text, nullable=True)
    sql_task = db.Column(db.Text, nullable=True)
    sql_instruction = db.Column(db.Text, nullable=True)

    rag_system_prompt = db.Column(db.Text, nullable=True)
    rag_task = db.Column(db.Text, nullable=True)
    rag_instruction = db.Column(db.Text, nullable=True)

    synthesizer_system_prompt = db.Column(db.Text, nullable=True)
    synthesizer_task = db.Column(db.Text, nullable=True)
    synthesizer_instruction = db.Column(db.Text, nullable=True)
    agent_type = db.Column(db.String(20), nullable=False, default="structured")  

    data_connection_id = db.Column(db.Integer, db.ForeignKey("data_source_connections.id"), nullable=True)
    data_connection = db.relationship("DataSourceConnection", back_populates="agents")
    tables = db.relationship("AgentTableMap", back_populates="agent", cascade="all, delete-orphan")
    query_log = db.relationship("QueryLog", back_populates="agent")
    dashboards = db.relationship("Dashboard", back_populates="agent", cascade="all, delete-orphan")
    glossary_items = db.relationship("BusinessGlossary", back_populates="agent", cascade="all, delete-orphan")
    chunks = db.relationship("Chunk", back_populates="agent", cascade="all, delete-orphan")
    files = db.relationship("AgentFileMap", back_populates="agent", cascade="all, delete-orphan")

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    is_deleted = db.Column(db.Boolean, server_default=db.false(), nullable=False)

    def delete(self):
        self.is_deleted = True
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "llm_model": self.llm_model,
            "llm_provider": self.llm_provider,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "data_connection_name": self.data_connection.source_name if self.data_connection else None,
            "data_connection_id": self.data_connection_id,
            "user_id": self.user_id,
            "sql_system_prompt": self.sql_system_prompt,
            "sql_task": self.sql_task,
            "sql_instruction": self.sql_instruction,
            "synthesizer_system_prompt": self.synthesizer_system_prompt,
            "synthesizer_task": self.synthesizer_task,
            "synthesizer_instruction": self.synthesizer_instruction,
            "rag_system_prompt": self.rag_system_prompt,
            "rag_task": self.rag_task,
            "rag_instruction": self.rag_instruction,
            "agent_type": self.agent_type,
            "status": self.status,
            "created_at": self.created_at
        }

    def __repr__(self):
        return f"<Agent {self.name}>"
    
class AgentTableMap(db.Model):
    __tablename__ = 'agent_table_map'

    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), nullable=False)
    table_id = db.Column(db.Integer, db.ForeignKey("table_of_uploadedfiles_metadata.id"), nullable=False)

    agent = db.relationship("Agent", back_populates="tables")
    table = db.relationship("TableMetadata", back_populates="agentmap")

    def __init__(self, agent_id=None, table_id=None):
        self.agent_id = agent_id
        self.table_id = table_id

    def to_dict(self):
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "table_id": self.table_id,
            "table_name": self.table.table_name
        }

    def __repr__(self):
        return f"<AgentTableMap(agent_id={self.agent_id}, table_id={self.table_id})>"

class AgentFileMap(db.Model):
    __tablename__ = 'agent_file_map'
    id = db.Column(db.Integer, primary_key=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), nullable=False)
    file_id = db.Column(db.Integer, db.ForeignKey("file_metadata.id"), nullable=False)

    agent = db.relationship("Agent", back_populates="files")
    file = db.relationship("FileMetadata", back_populates="agents")

    def __init__(self, agent_id=None, file_id=None):
        self.agent_id = agent_id
        self.file_id = file_id
    def to_dict(self):
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "file_id": self.file_id,
            "file_name": self.file.original_filename
        }

    def __repr__(self):
        return f"<AgentFileMap(agent_id={self.agent_id}, file_id={self.file_id})>"

class BusinessGlossary(db.Model):
    __tablename__ = 'business_glossary'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    agent_id = db.Column(db.Integer, db.ForeignKey("agents.id"), nullable=False)
    term = db.Column(db.String(255), nullable=False)
    definition = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())

    agent = db.relationship("Agent", back_populates="glossary_items")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "term": self.term,
            'agent': self.agent.to_dict(),
            "definition": self.definition,
            "category": self.category,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }