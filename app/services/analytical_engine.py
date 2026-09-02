import json
from sqlalchemy import text
from app.extensions import db
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
import os
import re

ALLOWED_TABLES = {"event_fact"}
ALLOWED_COLUMNS = {
    "event_text",
    "normalized_event_text",
    "event_date",
    "event_time",
    "event_datetime",
    "file_metadata_id",
    "contains_overlast"
}

FORBIDDEN_KEYWORDS = [
    "update",
    "delete",
    "insert",
    "drop",
    "alter",
    "truncate",
    "create",
    "grant",
    "revoke",
    "commit",
    "rollback",
]

def validate_and_inject_scope(sql: str) -> str:
    if not sql:
        raise ValueError("Empty SQL generated")

    # Normalize
    sql_clean = sql.strip()
    sql_lower = sql_clean.lower()

    # ----------------------------------------
    # 1️⃣ Only allow SELECT
    # ----------------------------------------
    if not sql_lower.startswith("select"):
        raise ValueError("Only SELECT statements are allowed")

    # ----------------------------------------
    # 2️⃣ Block multiple statements
    # ----------------------------------------
    if ";" in sql_clean:
        raise ValueError("Multiple statements not allowed")

    # ----------------------------------------
    # 3️⃣ Block SQL comments
    # ----------------------------------------
    if "--" in sql_clean or "/*" in sql_clean:
        raise ValueError("SQL comments are not allowed")

    # ----------------------------------------
    # 4️⃣ Block forbidden keywords
    # ----------------------------------------
    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", sql_lower):
            raise ValueError(f"Forbidden keyword detected: {keyword}")

    # ----------------------------------------
    # 5️⃣ Block UNION (data exfiltration vector)
    # ----------------------------------------
    if re.search(r"\bunion\b", sql_lower):
        raise ValueError("UNION is not allowed")

    # ----------------------------------------
    # 6️⃣ Ensure only allowed tables used
    # ----------------------------------------
    table_matches = re.findall(r"\bfrom\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql_lower)
    if not table_matches:
        raise ValueError("No FROM clause found")

    for table in table_matches:
        if table not in ALLOWED_TABLES:
            raise ValueError(f"Unauthorized table used: {table}")

    # ----------------------------------------
    # 7️⃣ Optional: Basic column whitelist
    # ----------------------------------------
    select_match = re.search(r"select\s+(.*?)\s+from", sql_lower, re.DOTALL)
    if select_match:
        select_part = select_match.group(1)

        # remove count(*) case
        if "count(" not in select_part:
            columns = [
                col.strip().split(" as ")[0]
                for col in select_part.split(",")
            ]

            for col in columns:
                col = col.replace("event_fact.", "").strip()

                # Remove function wrappers like COUNT(...)
                col = re.sub(r"\bcount\s*\(.*?\)", "count", col, flags=re.IGNORECASE)
                col = re.sub(r"\bdate\s*\(.*?\)", "", col, flags=re.IGNORECASE).strip()

                if col != "*" and col not in ALLOWED_COLUMNS:
                    raise ValueError(f"Unauthorized column: {col}")

    # ----------------------------------------
    # 8️⃣ Inject agent isolation safely
    # ----------------------------------------
    agent_scope = """
    event_fact.file_metadata_id IN (
        SELECT file_metadata_id
        FROM agent_file_map
        WHERE agent_id = :agent_id
    )
    """

    if re.search(r"\bwhere\b", sql_lower):
        sql_injected = re.sub(
            r"\bwhere\b",
            f"WHERE ({agent_scope}) AND ",
            sql_clean,
            count=1,
            flags=re.IGNORECASE
        )
    else:
        sql_injected = f"{sql_clean} WHERE {agent_scope}"

    return sql_injected


# --------------------------------------------------
# Entry point
# --------------------------------------------------

def run_analytical_engine(agent_id: int, analysis: dict, glossary: dict) -> dict:
    sql_query = generate_sql_from_llm(analysis, glossary)
    print('[run_analytical_engine]', sql_query)

    validated_sql = validate_and_inject_scope(sql_query)

    result = db.session.execute(
        text(validated_sql),
        {"agent_id": agent_id}
    ).fetchall()

    print('[run_analytical_engine]', result)

    return {
        "engine": "ai_sql",
        "sql": validated_sql,
        "rows": [dict(r._mapping) for r in result],
        "result": len(result)
    }


def generate_sql_from_llm(analysis: dict, glossary: dict = None) -> str:
    llm = ChatOpenAI(
        temperature=0,
        model="gpt-4o-mini",
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )

    glossary_text = json.dumps(glossary or {}, indent=2)

    system_prompt = f"""
You are a deterministic SQL generator for SQLite.

━━━━━━━━━━━━━━━━━━━━━━
BUSINESS GLOSSARY
━━━━━━━━━━━━━━━━━━━━━━
The following glossary contains canonical terms and allowed synonyms.
Only use synonyms explicitly listed.
Do NOT invent synonyms.

Glossary:
{glossary_text}

━━━━━━━━━━━━━━━━━━━━━━
STRICT RULES
━━━━━━━━━━━━━━━━━━━━━━
- Only generate a SELECT query.
- Only use table: event_fact.
- Allowed columns:
    - event_text
    - normalized_event_text
    - event_date
    - event_time
    - event_datetime
    - file_metadata_id
    - contains_overlast

- NEVER include agent filtering.
- NEVER include UPDATE, DELETE, INSERT, DROP.
- No semicolons.
- No UNION.
- Output SQL only.

━━━━━━━━━━━━━━━━━━━━━━
FILTERING RULES
━━━━━━━━━━━━━━━━━━━━━━
- Use canonical keyword from analysis.entities.keywords.
- If glossary_expanded exists:
    - Include canonical term in LIKE filter.
    - Include synonyms using OR.
    - Example:
        (event_text LIKE '%canonical%' OR event_text LIKE '%synonym%')

- If canonical term relates to overlast:
    Prefer:
        contains_overlast = 1

━━━━━━━━━━━━━━━━━━━━━━
DATE RULE
━━━━━━━━━━━━━━━━━━━━━━
Use SQLite syntax:
- datetime('now', '-7 days')
- date('now')

Do NOT guess time ranges.
Only use time filters explicitly present in analysis.
"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=json.dumps(analysis))
    ]

    response = llm.invoke(messages)

    return response.content.strip()

# --------------------------------------------------
# Operation implementations
# --------------------------------------------------

def exact_count(agent_id: int, entities: dict) -> dict:
    phrase = entities.get("event_phrase")
    keyword = entities.get("keywords", [None])[0]

    print(phrase, keyword)

    if not phrase and not keyword:
        raise ValueError("exact_count requires keyword or event_phrase")

    sql = """
    SELECT COUNT(*)
    FROM event_fact
    WHERE event_fact.file_metadata_id IN (
        SELECT file_metadata_id
        FROM agent_file_map
        WHERE agent_id = :agent_id
    )
    AND normalized_event_text LIKE :pattern
    """

    pattern = phrase or keyword

    result = db.session.execute(
        text(sql),
        {"agent_id": agent_id, "pattern": f"%{pattern}%"}
    ).scalar()

    print(result)

    return {
        "engine": "analytical",
        "operation_type": "exact_count",
        "result": int(result or 0)
    }

def unique_count(agent_id: int, entities: dict) -> dict:
    phrase = entities.get("event_phrase")
    if not phrase:
        raise ValueError("unique_count requires event_phrase")

    sql = """
    SELECT COUNT(DISTINCT timestamp)
    FROM event_fact
    WHERE event_fact.file_metadata_id IN (
        SELECT file_metadata_id
        FROM agent_file_map
        WHERE agent_id = :agent_id
    )
    AND normalized_event_text LIKE :phrase
    AND timestamp IS NOT NULL
    """

    result = db.session.execute(
        text(sql),
        {"agent_id": agent_id, "phrase": f"%{phrase}%"}
    ).scalar()

    return {
        "engine": "analytical",
        "operation_type": "unique_count",
        "result": int(result or 0)
    }

def contains_filter(agent_id: int, entities: dict) -> dict:
    keyword = entities.get("keywords", [None])[0]
    if not keyword:
        raise ValueError("contains_filter requires keyword")

    sql = """
    SELECT event_text, timestamp
    FROM event_fact
    WHERE event_fact.file_metadata_id IN (
        SELECT file_metadata_id
        FROM agent_file_map
        WHERE agent_id = :agent_id
    )
    AND normalized_event_text LIKE :kw
    ORDER BY timestamp
    """

    rows = db.session.execute(
        text(sql),
        {"agent_id": agent_id, "kw": f"%{keyword}%"}
    ).fetchall()

    return {
        "engine": "analytical",
        "operation_type": "contains_filter",
        'result': len(rows),
        "rows": [dict(r._mapping) for r in rows]
    }

def aggregation(agent_id: int, entities: dict) -> dict:
    keyword = entities.get("keywords", [None])[0]

    where_clause = """
    WHERE event_fact.file_metadata_id IN (
        SELECT file_metadata_id
        FROM agent_file_map
        WHERE agent_id = :agent_id
    )
    """

    params = {"agent_id": agent_id}

    if keyword:
        where_clause += " AND normalized_event_text LIKE :kw"
        params["kw"] = f"%{keyword}%"

    sql = f"""
    SELECT timestamp, COUNT(*) AS count
    FROM event_fact
    {where_clause}
    GROUP BY timestamp
    ORDER BY timestamp
    """

    rows = db.session.execute(text(sql), params).fetchall()

    return {
        "engine": "analytical",
        "operation_type": "aggregation",
        "rows": [dict(r._mapping) for r in rows],
        "result": len(rows)
    }
