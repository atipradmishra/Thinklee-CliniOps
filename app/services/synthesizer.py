from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage


def build_synthesizer_system_prompt(language: str):
    return f"""
You are a conversational AI assistant.

Rules:
- You are continuing an ongoing chat
- Do NOT mention internal systems, routing, or engines
- Do NOT repeat the user's question
- Explain results in simple, natural language
- Keep responses concise and friendly
- If the answer is partial or unclear, gently ask a follow-up
- Respond in {language}
"""


def build_synthesizer_payload(
    raw_answer: str,
    analysis: dict,
    chat_history
):
    return f"""
Conversation so far:
{chat_history or "No previous conversation"}

User intent:
{analysis.get("intent_summary") or analysis.get("normalized_query")}

Raw result (internal):
{raw_answer}

Now respond naturally to the user.
"""


def synthesize_response(
    *,
    raw_answer: str,
    analysis: dict,
    chat_history,
    language: str
) -> str:
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.4,
        max_retries=2,
        timeout=20
    )

    response = llm.invoke([
        SystemMessage(content=build_synthesizer_system_prompt(language)),
        HumanMessage(content=build_synthesizer_payload(
            raw_answer=raw_answer,
            analysis=analysis,
            chat_history=chat_history
        ))
    ])

    return response.content.strip()
