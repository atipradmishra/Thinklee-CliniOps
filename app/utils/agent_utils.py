from app.models.data_connection import DataSourceConnection
from app.models.table_metadata import TableMetadata
from app.utils.db_connections import DISPLAY_NAMES, OBJECT_STORE_TYPES


def is_agent_queryable(agent):
    # -------------------------------
    # Structured agent → DB connection
    # -------------------------------
    if agent.agent_type == "structured" and agent.data_connection_id:
        conn = DataSourceConnection.query.filter_by(
            id=agent.data_connection_id,
            is_deleted=False
        ).first()

        if not conn:
            return {
                "status": False,
                "reason": "Invalid or deleted DB connection"
            }

        # Object stores hold files, not tables. Reporting them as queryable
        # sent the SQL agent down a path that crashed on a NULL password.
        if conn.source_type in OBJECT_STORE_TYPES:
            label = DISPLAY_NAMES.get(conn.source_type, conn.source_type)
            return {
                "status": False,
                "reason": (
                    f"{label} stores files rather than tables, so it cannot be "
                    "queried directly. Import objects from it under Data "
                    "Management, then point this agent at the resulting tables."
                )
            }

        return {
            "status": True,
            "type": "db",
            "db_type": conn.source_type,
            "table_names": None
        }

    # -------------------------------
    # Structured agent → selected tables
    # -------------------------------
    elif agent.agent_type == "structured" and agent.tables:
        table_ids = [m.table_id for m in agent.tables]

        tables = (
            TableMetadata.query
            .filter(
                TableMetadata.id.in_(table_ids),
                TableMetadata.is_deleted.is_(False)
            )
            .all()
        )

        table_names = [t.table_name for t in tables]

        if not table_names:
            return {
                "status": False,
                "reason": "No valid (non-deleted) tables connected"
            }

        return {
            "status": True,
            "type": "tables",
            "db_type": "rootDb",
            "table_names": table_names
        }

    # -------------------------------
    # Unstructured (RAG)
    # -------------------------------
    elif agent.agent_type == "unstructured":
        return {
            "status": True,
            "type": "rag",
            "db_type": "vectorstore",
            "table_names": None
        }

    # -------------------------------
    # Fallback
    # -------------------------------
    return {
        "status": False,
        "reason": "No active data source, tables, or documents connected"
    }
