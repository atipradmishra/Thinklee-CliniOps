"""Read-only, agent-scoped execution shared by graphs and dashboard widgets."""
import sqlite3
import sqlglot
from sqlglot import exp
from sqlalchemy import text
from app.extensions import db
from app.utils.agent_utils import is_agent_queryable
from app.utils.db_connections import create_source_engine

MAX_ROWS = 2000
SAFE_FUNCTIONS = set('''ABS AVG CEIL CEILING COALESCE CONCAT CONCAT_WS COUNT CUME_DIST
DATE DATE_ADD DATE_DIFF DATE_SUB DATE_TRUNC DATETIME DATETIME_ADD DATETIME_DIFF
DAY DAY_OF_MONTH DAY_OF_WEEK DAY_OF_YEAR DENSE_RANK EXTRACT FLOOR GREATEST IF
IFNULL IIF LAG LAST_DAY LEAD LEAST LENGTH LOWER MAX MIN MOD MONTH NULLIF
NTILE PERCENT_RANK POWER RANK REPLACE ROUND ROW_NUMBER SIGN SQRT STDDEV
STDDEV_POP STDDEV_SAMP SUBSTRING SUM TIME TIMESTAMP TIMESTAMP_ADD TIMESTAMP_DIFF
TIMESTAMP_TRUNC TRIM UPPER VARIANCE VAR_POP VAR_SAMP WEEK YEAR CAST TRY_CAST
CURRENT_DATE CURRENT_TIME CURRENT_TIMESTAMP TIME_TO_STR STR_TO_TIME STR_TO_DATE
TS_OR_DS_TO_DATE TS_OR_DS_TO_TIMESTAMP UNIX_TO_TIME TIME_TO_UNIX
ARRAY_AGG GROUP_CONCAT FIRST_VALUE LAST_VALUE NTH_VALUE DATE_FROM_PARTS
CASE AND OR NOT'''.split())
# SQLGlot represents several SQLite built-ins as Anonymous expressions.
# Permit these by dialect and exact name, never arbitrary user-defined functions.
SQLITE_FUNCTIONS = {'DATE', 'TIME', 'DATETIME', 'JULIANDAY', 'STRFTIME', 'UNIXEPOCH'}


def validate_sql(sql, dialect='sqlite'):
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError('A SQL query is required.')
    dialect = {'postgresql': 'postgres', 'mssql': 'tsql'}.get(dialect, dialect)
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except sqlglot.errors.ParseError as exc:
        raise ValueError('Invalid reporting SQL.') from exc
    if len(statements) != 1 or not isinstance(statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise ValueError('Only a single read-only SELECT query is allowed.')
    forbidden = {'Insert', 'Update', 'Delete', 'Create', 'Drop', 'Alter', 'Command',
                 'Into', 'Lock', 'Copy', 'Merge', 'Transaction', 'Grant', 'Revoke'}
    for node in statements[0].walk():
        if isinstance(node, exp.Anonymous):
            if dialect == 'sqlite' and node.name.upper() in SQLITE_FUNCTIONS:
                continue
            raise ValueError(f'The {node.name} function is not supported in reporting SQL.')
        if type(node).__name__ in forbidden:
            raise ValueError('This operation or custom function is not allowed in reporting SQL.')
        if isinstance(node, exp.Func) and node.sql_name() not in SAFE_FUNCTIONS:
            raise ValueError(f'The {node.sql_name()} function is not supported in reporting SQL.')
    return statements[0]


def local_tables(agent):
    return {f'org_{agent.organization_id}_{m.table.table_name}'.lower()
            for m in agent.tables if m.table and not m.table.is_deleted
            and m.table.organization_id == agent.organization_id}


def execute_report_query(agent, sql):
    info = is_agent_queryable(agent)
    if not info['status'] or info['type'] not in ('tables', 'db') or agent.is_deleted:
        raise ValueError('Connect an active structured data source to this agent.')
    external = info['type'] == 'db'
    if external:
        source = agent.data_connection
        if source.organization_id != agent.organization_id or source.user_id != agent.user_id:
            raise ValueError('Data source access denied.')
        engine = create_source_engine(source)
    else:
        engine = db.engine
    try:
        tree = validate_sql(sql, engine.dialect.name)
        if not external and any(table.catalog or table.db.lower() not in ('', 'main')
                                for table in tree.find_all(exp.Table)):
            raise ValueError('Only this agent\'s assigned tables may be queried.')
        dialect = {'postgresql': 'postgres', 'mssql': 'tsql'}.get(engine.dialect.name, engine.dialect.name)
        # Execute the parsed statement, without executable vendor comments.
        sql = tree.sql(dialect=dialect, comments=False)
        with engine.connect() as connection:
            raw = None
            if not external:
                # SQLite's authorizer checks every actual read, including CTEs,
                # subqueries and views. Never trust table names from the prompt.
                if engine.dialect.name != 'sqlite':
                    raise ValueError('Uploaded-table reporting requires SQLite isolation.')
                allowed = local_tables(agent)
                raw = connection.connection.driver_connection
                def authorize(action, arg1, arg2, database, trigger):
                    if action == sqlite3.SQLITE_READ:
                        # SQLite emits database=None, column='' for table-only
                        # reads such as optimized COUNT(*). Still require the
                        # exact assigned table; ordinary column reads need main.
                        valid_database = database == 'main' or (database is None and arg2 == '')
                        return sqlite3.SQLITE_OK if valid_database and (arg1 or '').lower() in allowed else sqlite3.SQLITE_DENY
                    if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
                        return sqlite3.SQLITE_OK
                    if action == sqlite3.SQLITE_FUNCTION and (arg2 or '').lower() not in ('load_extension', 'readfile', 'writefile'):
                        return sqlite3.SQLITE_OK
                    return sqlite3.SQLITE_DENY
                raw.set_authorizer(authorize)
            try:
                if external and engine.dialect.name in ('mysql', 'postgresql'):
                    connection.execute(text('SET TRANSACTION READ ONLY'))
                result = connection.execute(text(sql))
                rows = [dict(row._mapping) for row in result.fetchmany(MAX_ROWS + 1)]
                if len(rows) > MAX_ROWS:
                    raise ValueError(f'Too many results. Aggregate or limit the query to {MAX_ROWS} rows.')
                return rows
            finally:
                if raw is not None:
                    raw.set_authorizer(None)
    finally:
        if external:
            engine.dispose()
