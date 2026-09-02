from app.models.agent import AgentFileMap
from app.models.file_metadata import FileMetadata
from app.extensions import db


def get_agent_storage_language(agent_id: int) -> str:
    """
    Returns dominant storage language for an agent.
    Defaults to 'unknown' if not found.
    """

    result = (
        db.session.query(FileMetadata.language)
        .join(AgentFileMap, AgentFileMap.file_id == FileMetadata.id)
        .filter(
            AgentFileMap.agent_id == agent_id,
            FileMetadata.is_deleted.is_(False)
        )
        .group_by(FileMetadata.language)
        .order_by(db.func.count(FileMetadata.language).desc())
        .first()
    )

    if result and result[0]:
        return result[0]

    return "unknown"
