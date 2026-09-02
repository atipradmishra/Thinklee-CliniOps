import json
import os
from app.services.analytical_engine import run_analytical_engine
from sqlalchemy import text
from app.extensions import db
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

# --------------------------------------------------
# Entry point
# --------------------------------------------------

def run_hybrid_engine(
        agent_id: int,
        analysis: dict,
        glossary_text: str | None = None,
        chat_history: list | None = None,
    ):
    """
    Hybrid Engine:
    - SQL computes facts (counts, events, filters)
    - LLM explains ONLY the computed results
    """

    # ---------- Step 1: Execute Analytical Core ----------
    analytical_result = run_analytical_engine(
        agent_id=agent_id,
        analysis=analysis
    )

    facts = analytical_result["facts"]
    chunks = analytical_result.get("chunks", [])

    # ---------- Safety Guard ----------
    if not facts:
        return {
            "answer": "No relevant data was found for this query.",
            "chunks": [],
        }

    # ---------- Step 2: Build Locked Explanation Prompt ----------
    system_prompt = build_hybrid_explainer_prompt(
        language=analysis["language"]
    )

    user_prompt = build_hybrid_user_payload(
        query=analysis["normalized_query"],
        facts=facts,
        glossary_text=glossary_text,
        chat_history=chat_history,
    )

    # ---------- Step 3: LLM Invocation ----------
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.1,  # low creativity = less risk
        max_retries=2,
        timeout=20,
    )

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])

    return {
        "answer": response.content.strip(),
        "chunks": chunks,
    }



# --------------------------------------------------
# SQL layer (exact filtering)
# --------------------------------------------------

def fetch_rows(entities: dict) -> list[dict]:
    keyword = entities.get("keywords", [None])[0]
    event_phrase = entities.get("event_phrase")
    time_constraint = entities.get("time_constraint")

    where_clauses = []
    params = {}

    if event_phrase:
        where_clauses.append("normalized_event_text LIKE :phrase")
        params["phrase"] = f"%{event_phrase}%"

    if keyword:
        where_clauses.append("normalized_event_text LIKE :kw")
        params["kw"] = f"%{keyword}%"

    if time_constraint == "after 18:00":
        where_clauses.append("timestamp >= '18:00'")

    where_sql = " AND ".join(where_clauses)
    if where_sql:
        where_sql = "WHERE " + where_sql

    sql = f"""
    SELECT event_text, timestamp
    FROM event_fact
    {where_sql}
    ORDER BY timestamp
    """

    rows = db.session.execute(text(sql), params).fetchall()
    return [dict(r._mapping) for r in rows]


# --------------------------------------------------
# LLM Context Builder
# --------------------------------------------------

def build_llm_context(rows: list[dict], max_events: int = 50) -> str:
    """
    Compress events into a bounded context window.
    """
    lines = []

    for row in rows[:max_events]:
        ts = row.get("timestamp") or "--"
        lines.append(f"[{ts}] {row['event_text']}")

    if len(rows) > max_events:
        lines.append(f"...and {len(rows) - max_events} more events")

    return "\n".join(lines)


# --------------------------------------------------
# LLM Summarization
# --------------------------------------------------

def summarize_with_llm(normalized_query: str, context: str) -> str:
    llm = ChatOpenAI(
        temperature=0,
        model="gpt-4o-mini",
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        max_retries=2,
        timeout=20,
    )

    system_prompt = """
You are a summarization assistant.

Rules:
- Use ONLY the provided events.
- Do NOT invent facts.
- Do NOT count or calculate numbers unless explicitly present.
- Produce a concise, factual summary.
""".strip()

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(
            content=f"User question: {normalized_query}\n\nEvents:\n{context}"
        )
    ]

    response = llm.invoke(messages)
    return response.content.strip()


def build_hybrid_explainer_prompt(language: str) -> str:
    return f"""
You are a Hybrid Explanation Engine.

You are given VERIFIED FACTS computed by a database.
These facts are CORRECT and FINAL.

STRICT RULES (NON-NEGOTIABLE):
- Do NOT recompute counts or totals
- Do NOT infer missing data
- Do NOT introduce new numbers
- Do NOT contradict the provided facts
- Do NOT guess causes or trends unless explicitly stated
- Do NOT mention SQL, databases, or analysis steps

Your ONLY task:
- Explain the provided facts clearly and naturally
- Preserve all numbers EXACTLY as given
- Use the same language as the user ({language})

If facts are insufficient, say:
"The available data does not provide enough detail to answer that."

Respond with explanation ONLY.
""".strip()

def build_hybrid_user_payload(
        query: str,
        facts: dict,
        glossary_text: str | None = None,
        chat_history: list | None = None,
    ) -> str:
    payload = []

    payload.append("USER QUESTION:")
    payload.append(query)

    payload.append("\nVERIFIED FACTS (DO NOT CHANGE):")
    payload.append(json.dumps(facts, indent=2, ensure_ascii=False))

    if glossary_text:
        payload.append("\nBUSINESS GLOSSARY:")
        payload.append(glossary_text)

    if chat_history:
        payload.append("\nCHAT HISTORY (FOR CONTEXT ONLY):")
        payload.append(json.dumps(chat_history[-3:], indent=2))

    payload.append(
        "\nExplain the VERIFIED FACTS in plain language. "
        "Do not add or change any numbers."
    )

    return "\n".join(payload)
