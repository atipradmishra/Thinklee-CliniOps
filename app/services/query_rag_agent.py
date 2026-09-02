import json
from typing import List, Tuple, Union
import os
from app.models.file_metadata import FileMetadata
from app.services.analytical_engine import run_analytical_engine
from app.services.hybrid_engine import run_hybrid_engine
from app.services.query_analyzer_agent import analyze_query
from app.services.synthesizer import synthesize_response
from app.utils.helpers import get_agent_storage_language
import numpy as np
from flask_jwt_extended import verify_jwt_in_request
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.models.agent import Agent, AgentFileMap
from app.models.chunks import Chunk
from app.utils.embeding_utils import get_embeddings
from app.extensions import db

def safe_normalize_embedding(embedding_data: Union[str, List[float], np.ndarray]) -> np.ndarray:

    try:
        if isinstance(embedding_data, str):
            embedding_data = json.loads(embedding_data.strip())

        vec = np.array(embedding_data, dtype=np.float32)

        if vec.size == 0:
            raise ValueError("Empty embedding vector")
        
        if not np.isfinite(vec).all():
            raise ValueError("Embedding contains NaN or infinite values")
        
        norm = np.linalg.norm(vec)
        if norm == 0:
            return vec
        
        return vec / norm
        
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in embedding: {str(e)}")
    except (TypeError, ValueError) as e:
        raise ValueError(f"Cannot process embedding: {str(e)}")

def normalize(vec: List[float]) -> np.ndarray:
    v = np.array(vec, dtype=np.float32)
    n = np.linalg.norm(v)
    return v / n if n > 0 else v

def mmr(
    query_vec: np.ndarray,
        candidates: List[Tuple[str, np.ndarray, dict]],
        k: int = 5,
        lambda_mult: float = 0.7
    ) -> List[Tuple[str, np.ndarray, dict]]:

    # ---------- Guardrails ----------
    if k <= 0 or not candidates:
        return []

    if not isinstance(query_vec, np.ndarray) or query_vec.ndim != 1:
        raise ValueError("query_vec must be a 1D numpy array")

    # Clamp lambda to safe range
    lambda_mult = float(np.clip(lambda_mult, 0.0, 1.0))

    # Ensure float32 for stable dot products
    query_vec = query_vec.astype(np.float32, copy=False)

    selected: List[Tuple[str, np.ndarray, dict]] = []
    remaining = candidates.copy()

    # ---------- MMR Loop ----------
    while remaining and len(selected) < k:
        best_idx = -1
        best_score = -np.inf

        for idx, (text, emb, meta) in enumerate(remaining):

            if not isinstance(emb, np.ndarray) or emb.ndim != 1:
                continue  # skip malformed embeddings

            emb = emb.astype(np.float32, copy=False)

            # Cosine similarity (assumes normalized vectors)
            relevance = float(np.dot(query_vec, emb))

            # Redundancy against already selected items
            redundancy = 0.0
            if selected:
                redundancy = max(
                    float(np.dot(emb, sel_emb))
                    for _, sel_emb, _ in selected
                )

            score = (lambda_mult * relevance) - ((1.0 - lambda_mult) * redundancy)

            if score > best_score:
                best_score = score
                best_idx = idx

        if best_idx == -1:
            break

        selected.append(remaining[best_idx])
        remaining.pop(best_idx)

    return selected

def mmr_multi_query(
        query_vectors: List[np.ndarray],
        candidates: List[Tuple[str, np.ndarray, dict]],
        k: int = 5,
        lambda_mult: float = 0.7
    ) -> List[Tuple[str, np.ndarray, dict]]:

    if not query_vectors or not candidates:
        return []

    # Step 1: run MMR for each query independently
    pooled = []
    for qv in query_vectors:
        pooled.extend(
            mmr(qv, candidates, k=k, lambda_mult=lambda_mult)
        )

    # Step 2: deduplicate by chunk id
    unique = {}
    for text, emb, meta in pooled:
        unique[meta["id"]] = (text, emb, meta)

    deduped = list(unique.values())

    # Step 3: final MMR using primary query
    return mmr(
        query_vectors[0],
        deduped,
        k=k,
        lambda_mult=lambda_mult
    )

def estimate_tokens(s: str) -> int:
    return max(1, len(s) // 4)

def budget_context(chunks: List[str], max_tokens: int) -> List[str]:
    out, used = [], 0
    for c in chunks:
        t = estimate_tokens(c)
        if used + t > max_tokens:
            break
        out.append(c)
        used += t
    return out

def build_rag_system_prompt(
    agent,
    detected_language: str = "auto"
):
    return f"""
You are a controlled AI response engine.

========================
ABSOLUTE RULES (NON-NEGOTIABLE)
========================

LANGUAGE POLICY (STRICT ENFORCEMENT):
- Answer ONLY in {detected_language}
- NEVER translate the question.
- NEVER mix languages.
- If detection is ambiguous, default to the user's language.
- If you violate this rule, your response is INVALID.

BEHAVIOR POLICY:
1. NEVER mention:
   - context
   - retrieval
   - documents
   - chunks
   - embeddings
   - tools
   - sources
   - internal steps
   - system instructions
2. NEVER explain how you obtained the answer.
3. NEVER cite, reference, or label sources.
4. NEVER include meta commentary or preambles.

5. If information is insufficient:
   - Ask ONE natural clarifying question
   - DO NOT mention missing context or documents

========================
STRUCTURED RFP ANALYSIS MODE
========================

If the user specifically asks to summarize, review, or analyze an RFP, proposal, contract, tender, or similar structured document:

You MUST structure the response exactly as follows:

1) High-Level Summary
   - 4–5 bullet points summarizing the overall objective and intent.

2) Scope
   - 4–5 bullet points detailing scope of work, deliverables, responsibilities.

3) Timeline
   - 4–5 bullet points covering milestones, deadlines, contract duration.

4) Budget / Commercials
   - 4–5 bullet points outlining pricing model, payment terms, cost structure (if available).

5) Acceptance Criteria
   - 4–5 bullet points describing success metrics, deliverable validation, performance standards.

6) Eligibility / Qualification Requirements
   - 4–5 bullet points covering bidder qualifications, certifications, experience requirements.

7) Key RFP Questions Identified
   - Extract important explicit or implicit questions from the RFP.
   - List them clearly as bullet points.

8) Answers to Identified RFP Questions
   - Provide direct, concise answers if the information is available.
   - If an answer cannot be derived, state: "Not explicitly specified."

FORMAT REQUIREMENTS:
- Use clear section headers exactly as listed above.
- Each section must contain 4–5 bullet points.
- Be precise and structured.
- Do NOT add extra sections unless clearly present in the document.
- Do NOT include commentary outside the required structure.

TONE:
- Clear
- Professional
- Executive-ready
- Analytical

VIOLATION CONSEQUENCE:
If any rule above is violated, the response is considered incorrect.

========================
ROLE
========================
You are the FINAL answer synthesizer.

Business role:
{agent.rag_system_prompt or "Provide structured RFP analysis and executive-ready summaries."}
""".strip()

def build_user_payload(query, context, chat_history, glossary_text, few_shot_examples):
    return f"""
    Conversation History:
    {chat_history or "None"}

    Business Glossary:
    {glossary_text or "None"}

    Examples:
    {few_shot_examples or "None"}

    Internal Knowledge (DO NOT MENTION):
    {context}

    User Question:
    {query}
    """.strip()

def generate_rag_response(
        agent: Agent,
        nl_query: str,
        glossary_text=None,
        chat_history=None,
        few_shot_examples=None,
        top_k: int = 10,
        max_context_tokens: int = 1800,
    ):

    print(f"[RAG Agent] chat_history: {chat_history}")

    verify_jwt_in_request()

    # ---------- Basic Guards ----------
    if not nl_query or not nl_query.strip():
        return {
            "response": "Please enter a valid question.",
            "chunks": [],
            "meta": {"engine": "none"}
        }

    # ---------- Step 1: Query Analysis ----------
    storage_language = get_agent_storage_language(agent.id)

    query_analysis = analyze_query(
        nl_query,
        chat_history=chat_history,
        storage_language=storage_language,
        glossary_text=glossary_text
    )

    print("query_analysis", query_analysis)

    routing = query_analysis.get("routing")
    operation_type = query_analysis.get("operation_type")
    needs_clarification = query_analysis.get("needs_clarification", False)

    # ---------- Step 2: Clarification Handling ----------
    # if needs_clarification:
    #     return {
    #         "response": query_analysis.get("clarifying_question"),
    #         "chunks": [],
    #         "meta": {
    #             "engine": "clarification",
    #             "analysis": query_analysis
    #         }
    #     }

    # ---------- Step 3: Analytical Engine ----------
    if routing == "analytical":
        print("analytical")
        result = run_analytical_engine(
            agent_id=agent.id,
            analysis=query_analysis,
            glossary=glossary_text
        )
        
        final_response = synthesize_response(
            raw_answer=result["rows"],
            analysis=query_analysis,
            chat_history=chat_history,
            language=query_analysis["user_language"]
        )

        return {
            "response": final_response,
            "chunks": [],
            "meta": {
                "engine": "analytical",
                "operation_type": operation_type,
                "analysis": query_analysis
            }
        }

    # ---------- Step 4: Hybrid Engine ----------
    if routing == "hybrid":
        result = run_hybrid_engine(
            agent_id=agent.id,
            analysis=query_analysis,
            glossary_text=glossary_text,
            chat_history=chat_history,
        )

        final_response = synthesize_response(
            raw_answer=result["result"],
            analysis=query_analysis,
            chat_history=chat_history,
            language=query_analysis["language"]
        )

        return {
            "response": final_response,
            "chunks": result.get("chunks", []),
            "meta": {
                "engine": "hybrid",
                "operation_type": operation_type,
                "analysis": query_analysis
            }
        }

    # ---------- Step 5: Semantic RAG Only ----------
    if routing != "semantic":
        return {
            "response": "Unsupported query type.",
            "chunks": [],
            "meta": {
                "engine": "none",
                "analysis": query_analysis
            }
        }

    # ---------- Safety Guard ----------
    if operation_type in {"exact_count", "unique_count", "aggregation"}:
        raise RuntimeError(
            f"Analytical operation '{operation_type}' reached semantic RAG"
        )

    # ---------- Step 6: Build Query Variants ----------
    normalized_query = query_analysis["normalized_query"]
    all_queries = [normalized_query]

    if few_shot_examples:
        all_queries.extend(few_shot_examples)

    # ---------- Step 7: Embedding (Semantic ONLY) ----------
    query_vectors = [
        normalize(get_embeddings(q))
        for q in all_queries
    ]

    # ---------- Step 8: Retrieve Chunks ----------
    file_ids = (
        db.session.query(AgentFileMap.file_id)
        .join(FileMetadata, FileMetadata.id == AgentFileMap.file_id)
        .filter(
            AgentFileMap.agent_id == agent.id,
            FileMetadata.is_deleted.is_(False)
        )
        .all()
    )
    file_ids = [fid for (fid,) in file_ids]

    if not file_ids:
        return {
            "response": "No documents available.",
            "chunks": [],
            "meta": {"reason": "no_docs"}
        }

    chunks = Chunk.query.filter(
        Chunk.file_metadata_id.in_(file_ids)
    ).all()

    if not chunks:
        return {
            "response": "No documents available.",
            "chunks": [],
            "meta": {"reason": "no_chunks"}
        }

    candidates = []
    for ch in chunks:
        try:
            emb = safe_normalize_embedding(ch.embedding_json)
            candidates.append(
                (ch.text, emb, {"id": ch.id, "file_id": ch.file_metadata_id})
            )
        except Exception:
            continue  # skip bad embeddings safely

    if not candidates:
        return {
            "response": "No usable document content found.",
            "chunks": [],
            "meta": {"reason": "invalid_embeddings"}
        }

    # ---------- Retrieval (Analyzer-aware MMR) ----------
    selected = mmr(
            query_vectors[0],
            candidates,
            k=top_k,
            lambda_mult=0.7
        )

    top_texts = [text for text, _, _ in selected]

    # ---------- Context Budgeting ----------
    context_chunks = budget_context(top_texts, max_context_tokens)
    context = "\n\n---\n\n".join(context_chunks)

    # ---------- Step 10: Prompt Construction ----------
    system_prompt = build_rag_system_prompt(
        agent=agent,
        detected_language=query_analysis["user_language"]
    )

    user_payload = build_user_payload(
        query=normalized_query,
        context=context,
        chat_history=chat_history,
        glossary_text=glossary_text,
        few_shot_examples=few_shot_examples or []
    )

    # ---------- Step 11: LLM Call ----------
    llm = ChatOpenAI(
        temperature=0.2,
        model="gpt-4o-mini",
        max_retries=2,
        timeout=20,
    )

    response = llm.invoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_payload),
    ])

    # ---------- Step 12: Final Response ----------
    return {
        "response": response.content.strip(),
        "meta": {
            "engine": "rag",
            "analysis": query_analysis
        }
    }
