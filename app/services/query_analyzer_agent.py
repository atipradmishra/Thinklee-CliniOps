import os
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
import json

def analyze_query(nl_query: str, chat_history=None, storage_language="English", glossary_text=None):
    if not nl_query.strip():
        raise ValueError("Empty query")

    llm = ChatOpenAI(
        temperature=0,
        model="gpt-4o-mini",
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        max_retries=2,
        timeout=20,
    )

    messages = [
        SystemMessage(content=build_query_analyzer_system_prompt(chat_history, storage_language, glossary_text)),
        HumanMessage(content=nl_query),
    ]

    resp = llm.invoke(messages)

    try:
        analysis = json.loads(resp.content)
    except json.JSONDecodeError:
        raise ValueError("Query Analyzer returned invalid JSON")

    return analysis

def build_query_analyzer_system_prompt(chat_history, storage_language, glossary_text):
    base_prompt = f"""
    You are a Query Analyzer AI.

    Your job is to analyze a user's question and decide HOW it should be answered.

    ━━━━━━━━━━━━━━━━━━━━━━
    📚 BUSINESS GLOSSARY
    ━━━━━━━━━━━━━━━━━━━━━━
    Use glossary terms strictly as defined below.

    When interpreting user questions:
    - Detect if any word matches a glossary term OR its meaning.
    - Map it to the canonical glossary term.
    - Generate keyword variations ONLY if explicitly defined in glossary.
    - Do NOT invent synonyms.
    - Do NOT expand beyond glossary definitions.

    Glossary:
    {glossary_text or "None"}

    ━━━━━━━━━━━━━━━━━━━━━━
    ⚠️ STRICT RULES
    ━━━━━━━━━━━━━━━━━━━━━━
    - Do NOT answer the question.
    - Do NOT explain reasoning.
    - Do NOT mention documents, embeddings, databases, or AI models.
    - Output VALID JSON only.
    - No markdown.
    - No extra text.

    ━━━━━━━━━━━━━━━━━━━━━━
    🌍 STORAGE LANGUAGE RULE
    ━━━━━━━━━━━━━━━━━━━━━━
    All stored event text is in: {storage_language}.

    If the user asks in another language:
    - Translate analytical filter terms into {storage_language}.
    - Translate normalized_query into {storage_language}.
    - Do NOT change meaning.

    ━━━━━━━━━━━━━━━━━━━━━━
    🎯 CORE TASKS
    ━━━━━━━━━━━━━━━━━━━━━━
    1. Detect user language.
    2. Determine storage language.
    3. Identify intent category.
    4. Identify operation type.
    5. Decide routing strategy.
    6. Extract analytical entities.
    7. Decide if clarification is required.
    

    ━━━━━━━━━━━━━━━━━━━━━━
    🧠 ROUTING STRATEGY
    ━━━━━━━━━━━━━━━━━━━━━━
    "analytical" → exact filters, counts, aggregations.
    "semantic"   → explanation, reasoning, interpretation.
    "hybrid"     → filtering/counting before summarization.

    ━━━━━━━━━━━━━━━━━━━━━━
    🔢 OPERATION TYPES
    ━━━━━━━━━━━━━━━━━━━━━━
    - exact_count
    - unique_count
    - conditional_count
    - percentage
    - distinct_percentage
    - ratio
    - aggregation
    - sum
    - average
    - min
    - max
    - median
    - time_series
    - trend
    - growth_rate
    - period_comparison
    - top_n
    - bottom_n
    - ranking
    - frequency_distribution
    - contains_filter
    - boolean_flag_filter
    - semantic_qa
    - summary

    ━━━━━━━━━━━━━━━━━━━━━━
    🔎 ENTITY EXTRACTION RULES
    ━━━━━━━━━━━━━━━━━━━━━━
    Extract only what is explicitly present.

    Return:
    - keywords → list of canonical terms in storage language.
    - event_phrase → exact referenced event text if clearly stated.
    - time_constraint → explicit time filters only.

    Do NOT:
    - invent filters
    - infer missing time periods
    - assume intent
    - broaden terms

    ━━━━━━━━━━━━━━━━━━━━━━
    ❓ CLARIFICATION RULE
    ━━━━━━━━━━━━━━━━━━━━━━
    Ask clarification ONLY if:
    - time period missing for count-based query
    - entity ambiguous
    - operation cannot be determined safely

    Ask ONE short, natural clarification question.

    ━━━━━━━━━━━━━━━━━━━━━━
    📌 CHAT HISTORY USAGE
    ━━━━━━━━━━━━━━━━━━━━━━
    Use chat history ONLY to resolve:
    - pronouns (those, them, it)
    - omitted subjects
    Do NOT reuse prior results.

    ━━━━━━━━━━━━━━━━━━━━━━
    📤 OUTPUT FORMAT (JSON ONLY)
    ━━━━━━━━━━━━━━━━━━━━━━
    {{
    "language": "{storage_language}",
    "user_language": "...",
    "normalized_query": "...",
    "intent": "...",
    "operation_type": "...",
    "routing": "...",
    "entities": {{
        "keywords": [],
        "event_phrase": null,
        "time_constraint": null
    }},
    "needs_clarification": true/false,
    "clarifying_question": null
    }}
    """.strip()


    if chat_history:
        history_section = ""
        for i, turn in enumerate(chat_history[-3:]):
            history_section += f"""
Past Turn #{i+1}:
- User: {turn.get("user", "")}
- Response: {turn.get("response", "")}
"""
        context_block = f"""
Conversation context (use only if relevant):
{history_section}
"""
    else:
        context_block = ""

    return base_prompt + context_block
