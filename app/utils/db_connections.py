"""Single source of truth for data-source connection handling.

Before this module the URI-building logic was copy-pasted into
query_sql_agent.data_source_query and graph_query_agent.data_source_query,
while the reachability checks lived as a third, differently-shaped copy in
data_controller. The three had already drifted: the query agents emitted
``mysql+pymysql://`` (pymysql is not a dependency) and hardcoded
"ODBC Driver 17 for SQL Server", and neither test endpoint knew about mssql
at all.

Everything now goes through build_sqlalchemy_url() / probe_connection().
"""

import base64
from urllib.parse import quote_plus

from sqlalchemy import create_engine, text


# --------------------------------------------------------------------------
# Source types
# --------------------------------------------------------------------------

# Managed services are stored under their own source_type so the UI can show
# the right fields and branding, but they speak an ordinary engine underneath.
RDS_ENGINES = {
    "mysql": "mysql",
    "mariadb": "mysql",
    "postgresql": "postgresql",
    "mssql": "mssql",
}

# source_type -> engine used to build the URL
DIRECT_ENGINES = {
    "mysql": "mysql",
    "postgresql": "postgresql",
    "mssql": "mssql",
    "sqlite": "sqlite",
    "snowflake": "snowflake",
    "azure_sql": "mssql",
}

# Source types that hold files rather than tables. These can be browsed and
# imported, but they can never back a SQL agent.
OBJECT_STORE_TYPES = {"s3"}

SQL_SOURCE_TYPES = set(DIRECT_ENGINES) | {"rds"}
ALL_SOURCE_TYPES = SQL_SOURCE_TYPES | OBJECT_STORE_TYPES

DEFAULT_PORTS = {
    "mysql": 3306,
    "postgresql": 5432,
    "mssql": 1433,
}

DISPLAY_NAMES = {
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "mssql": "SQL Server",
    "sqlite": "SQLite",
    "snowflake": "Snowflake",
    "s3": "Amazon S3",
    "rds": "AWS RDS",
    "azure_sql": "Azure SQL",
}


class ConnectionConfigError(ValueError):
    """Raised when a connection is missing fields needed to build a URL."""


# --------------------------------------------------------------------------
# Secret helpers
# --------------------------------------------------------------------------

def encode_secret(value):
    """Store secrets base64-encoded, matching the existing column format."""
    if not value:
        return None
    return base64.b64encode(str(value).encode()).decode()


def decode_secret(value):
    """Decode a stored secret, tolerating values that were saved in plain text."""
    if not value:
        return None
    try:
        return base64.b64decode(str(value).encode()).decode()
    except Exception:
        # Older rows (and hand-edited ones) may hold the raw value.
        return str(value)


# --------------------------------------------------------------------------
# ODBC driver discovery
# --------------------------------------------------------------------------

# Newest first; the first one actually installed wins.
_PREFERRED_ODBC_DRIVERS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "ODBC Driver 13.1 for SQL Server",
    "ODBC Driver 13 for SQL Server",
    "SQL Server Native Client 11.0",
    "SQL Server",
)


def available_odbc_drivers():
    try:
        import pyodbc
    except ImportError:
        return []
    try:
        return list(pyodbc.drivers())
    except Exception:
        return []


def resolve_odbc_driver(preferred=None):
    """Pick an installed SQL Server ODBC driver.

    The old code hardcoded "ODBC Driver 17 for SQL Server", which fails on any
    host that ships a different version. Honour an explicit choice when it is
    installed, otherwise take the newest available.
    """
    installed = available_odbc_drivers()

    if preferred:
        if not installed or preferred in installed:
            return preferred

    for candidate in _PREFERRED_ODBC_DRIVERS:
        if candidate in installed:
            return candidate

    if installed:
        return installed[0]

    raise ConnectionConfigError(
        "No SQL Server ODBC driver is installed on the server. "
        "Install 'ODBC Driver 18 for SQL Server' (msodbcsql18) and try again."
    )


# --------------------------------------------------------------------------
# Config normalisation
# --------------------------------------------------------------------------

def _get(cfg, *names, default=None):
    """Read the first present key/attribute, so request JSON and ORM rows
    can both be passed in."""
    for name in names:
        if isinstance(cfg, dict):
            if cfg.get(name) not in (None, ""):
                return cfg.get(name)
        else:
            value = getattr(cfg, name, None)
            if value not in (None, ""):
                return value
    return default


def normalize_config(cfg, decode_password=True):
    """Flatten a request payload or DataSourceConnection into one dict.

    ``decode_password`` is False for unsaved form payloads (already plaintext)
    and True for stored rows (base64).
    """
    source_type = (_get(cfg, "source_type") or "").strip().lower()

    password = _get(cfg, "pwd", "password")
    if decode_password:
        password = decode_secret(password)

    secret_key = _get(cfg, "s3_secret_key")
    if decode_password:
        secret_key = decode_secret(secret_key)

    rds_engine = (_get(cfg, "rds_engine", default="") or "").strip().lower()

    return {
        "source_type": source_type,
        "rds_engine": rds_engine,
        "username": _get(cfg, "uid", "username"),
        "password": password,
        "host": _get(cfg, "host", "server"),
        "port": _get(cfg, "port"),
        "database": _get(cfg, "sql_database", "database", "sf_database"),
        "driver": _get(cfg, "driver"),
        "snowflake_account": _get(cfg, "sf_account", "snowflake_account"),
        "snowflake_warehouse": _get(cfg, "warehouse", "snowflake_warehouse"),
        "snowflake_schema": _get(cfg, "schema", "snowflake_schema"),
        "sqlite_path": _get(cfg, "sqlite_path", "data_source"),
        "s3_access_key": _get(cfg, "s3_access_key"),
        "s3_secret_key": secret_key,
        "s3_region": _get(cfg, "s3_region"),
        "s3_bucket": _get(cfg, "s3_bucket"),
        "s3_prefix": _get(cfg, "s3_prefix"),
    }


def resolve_engine(cfg):
    """Return the underlying engine name for a normalised config."""
    source_type = cfg["source_type"]

    if source_type == "rds":
        engine = RDS_ENGINES.get(cfg.get("rds_engine") or "")
        if not engine:
            raise ConnectionConfigError(
                "Select an RDS engine (MySQL, MariaDB, PostgreSQL or SQL Server)."
            )
        return engine

    engine = DIRECT_ENGINES.get(source_type)
    if not engine:
        if source_type in OBJECT_STORE_TYPES:
            raise ConnectionConfigError(
                f"{DISPLAY_NAMES.get(source_type, source_type)} stores files, not tables. "
                "Import objects from it instead of querying it directly."
            )
        raise ConnectionConfigError(f"Unsupported source type: {source_type or '(none)'}")

    return engine


def _require(cfg, field, label):
    value = cfg.get(field)
    if value in (None, ""):
        raise ConnectionConfigError(f"{label} is required.")
    return value


# --------------------------------------------------------------------------
# URL building
# --------------------------------------------------------------------------

def build_sqlalchemy_url(cfg):
    """Build a SQLAlchemy URL from a config produced by normalize_config()."""
    engine = resolve_engine(cfg)

    if engine == "sqlite":
        path = cfg.get("sqlite_path") or cfg.get("database")
        if not path:
            raise ConnectionConfigError("SQLite file path is required.")
        return f"sqlite:///{path}"

    if engine == "snowflake":
        user = _require(cfg, "username", "Username")
        account = _require(cfg, "snowflake_account", "Snowflake account")
        database = _require(cfg, "database", "Database name")
        password = quote_plus(cfg.get("password") or "")
        url = (
            f"snowflake://{quote_plus(user)}:{password}@{account}/"
            f"{database}/{cfg.get('snowflake_schema') or 'PUBLIC'}"
            f"?account={account}"
        )
        if cfg.get("snowflake_warehouse"):
            url += f"&warehouse={cfg['snowflake_warehouse']}"
        return url

    host = _require(cfg, "host", "Host")
    user = _require(cfg, "username", "Username")
    database = _require(cfg, "database", "Database name")
    password = quote_plus(cfg.get("password") or "")
    port = cfg.get("port") or DEFAULT_PORTS.get(engine)

    if engine == "mysql":
        # mysql-connector-python is the declared dependency; the old
        # mysql+pymysql:// URLs referenced a driver that was never installed.
        return f"mysql+mysqlconnector://{quote_plus(user)}:{password}@{host}:{port}/{database}"

    if engine == "postgresql":
        return f"postgresql+psycopg2://{quote_plus(user)}:{password}@{host}:{port}/{database}"

    if engine == "mssql":
        driver = resolve_odbc_driver(cfg.get("driver"))
        url = (
            f"mssql+pyodbc://{quote_plus(user)}:{password}@{host}:{port}/{database}"
            f"?driver={quote_plus(driver)}"
        )
        # Azure SQL refuses unencrypted connections.
        if cfg.get("source_type") == "azure_sql":
            url += "&Encrypt=yes&TrustServerCertificate=no&Connection+Timeout=30"
        elif "18" in driver:
            # Driver 18 flipped the Encrypt default to yes; most self-managed
            # servers use a self-signed cert.
            url += "&Encrypt=optional"
        return url

    raise ConnectionConfigError(f"Unsupported engine: {engine}")


SQL_DIALECT_NAMES = {
    "mysql": "MySQL",
    "postgresql": "PostgreSQL",
    "mssql": "Microsoft SQL Server (T-SQL)",
    "sqlite": "SQLite",
    "snowflake": "Snowflake",
}


def sql_dialect_name(cfg, decode_password=True):
    """Human-readable dialect name for the SQL-generation prompt.

    Matters for the managed types: an agent on an RDS PostgreSQL instance must
    be told to write PostgreSQL, not "RDS".
    """
    try:
        normalized = normalize_config(cfg, decode_password=decode_password)
        return SQL_DIALECT_NAMES.get(resolve_engine(normalized), "SQL")
    except ConnectionConfigError:
        return "SQL"


def create_source_engine(cfg, decode_password=True, **engine_kwargs):
    """Create a SQLAlchemy Engine for a data source."""
    normalized = normalize_config(cfg, decode_password=decode_password)
    url = build_sqlalchemy_url(normalized)
    engine_kwargs.setdefault("pool_pre_ping", True)
    return create_engine(url, **engine_kwargs)


# --------------------------------------------------------------------------
# Reachability probe
# --------------------------------------------------------------------------

# Cheap statement that proves the session is usable, per engine.
_PING = {
    "mysql": "SELECT 1",
    "postgresql": "SELECT 1",
    "mssql": "SELECT 1",
    "sqlite": "SELECT 1",
    "snowflake": "SELECT CURRENT_VERSION()",
}


def probe_connection(cfg, decode_password=True, timeout=15):
    """Open a connection and run a trivial query.

    Returns ``(ok: bool, message: str)`` instead of raising, so callers can
    surface the reason to the user.
    """
    normalized = normalize_config(cfg, decode_password=decode_password)
    source_type = normalized["source_type"]

    if source_type in OBJECT_STORE_TYPES:
        from app.utils.s3_utils import probe_s3
        return probe_s3(normalized)

    try:
        engine_name = resolve_engine(normalized)
        url = build_sqlalchemy_url(normalized)
    except ConnectionConfigError as exc:
        return False, str(exc)

    connect_args = {}
    if engine_name in ("postgresql",):
        connect_args["connect_timeout"] = timeout
    elif engine_name == "mysql":
        connect_args["connection_timeout"] = timeout
    elif engine_name == "mssql":
        connect_args["timeout"] = timeout

    engine = None
    try:
        engine = create_engine(url, connect_args=connect_args, pool_pre_ping=False)
        with engine.connect() as connection:
            connection.execute(text(_PING.get(engine_name, "SELECT 1")))
        label = DISPLAY_NAMES.get(source_type, source_type)
        return True, f"{label} connection successful."
    except Exception as exc:
        return False, _friendly_error(engine_name, exc)
    finally:
        if engine is not None:
            engine.dispose()


def _friendly_error(engine_name, exc):
    """Turn driver stack-trace noise into something a user can act on."""
    raw = str(getattr(exc, "orig", exc)).strip()
    lowered = raw.lower()

    if "no such host" in lowered or "getaddrinfo" in lowered or "name or service not known" in lowered:
        return "Host not found. Check the server address."
    if "timed out" in lowered or "timeout expired" in lowered:
        return (
            "Connection timed out. Check the port and that the firewall / security "
            "group allows traffic from this server."
        )
    if "refused" in lowered:
        return "Connection refused. Check the host and port, and that the server accepts remote connections."
    if "password authentication failed" in lowered or "access denied" in lowered or "login failed" in lowered:
        return "Authentication failed. Check the username and password."
    if "does not exist" in lowered and "database" in lowered:
        return "That database does not exist on the server."
    if "data source name not found" in lowered or "im002" in lowered:
        return (
            "No usable SQL Server ODBC driver was found. Install "
            "'ODBC Driver 18 for SQL Server' on the application server."
        )
    if "certificate" in lowered or "ssl" in lowered:
        return f"TLS/SSL error: {raw[:200]}"

    return raw[:300] if raw else f"{type(exc).__name__}: connection failed"


# --------------------------------------------------------------------------
# Schema reflection
# --------------------------------------------------------------------------

def reflect_schema(engine, include_schemas=False, max_tables=200):
    """Return ``{table_name: [{name, type}, ...]}`` for prompt building."""
    from sqlalchemy import MetaData

    metadata = MetaData()
    metadata.reflect(bind=engine)

    schema = {}
    for table in list(metadata.tables.values())[:max_tables]:
        key = str(table.fullname if include_schemas else table.name)
        schema[key] = [
            {"name": column.name, "type": str(column.type)}
            for column in table.columns
        ]
    return schema
