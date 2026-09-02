import os
import pickle
from app.models.query_log import QueryLog
from sentence_transformers import SentenceTransformer
from typing import List
import numpy as np
import faiss

# model = SentenceTransformer(os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"))

model = SentenceTransformer("intfloat/multilingual-e5-large")

def get_embeddings(text: str, normalize: bool = False) -> List[float]:
    print("➡ Entered get_embeddings")

    if not text:
        raise ValueError("Input text must be a non-empty string.")

    try:
        print("➡ Before encode")
        embedding = model.encode(text, normalize_embeddings=normalize)
        print("➡ After encode")

        return embedding.tolist()

    except Exception as e:
        print(f"[get_embedding] Failed to encode text: {e}")
        return []

def get_similar_feedback(nl_query: str, threshold: float = 0.30, top_k: int = 1, agent_id: int = None):
    # print(f"[get_similar_feedback] Query: {nl_query}")

    # Get query embedding and normalize for cosine similarity
    query_embedding = model.encode(nl_query)
    query_embedding = np.array(query_embedding, dtype=np.float32)
    faiss.normalize_L2(query_embedding.reshape(1, -1))

    # Fetch all logs with feedback and embeddings
    logs = QueryLog.query.filter(
        QueryLog.feedback_comment.isnot(None),
        QueryLog.feedback_embedding.isnot(None),
        # Return an empty list if there is an exception
        QueryLog.agent_id == agent_id
    ).all()
    # print(f"[get_similar_feedback] Found {len(logs)} logs")

    if not logs:
        return []

    embeddings = []
    valid_logs = []
    for log in logs:
        try:
            raw_emb = log.feedback_embedding
            emb = pickle.loads(raw_emb)
            emb = np.array(emb, dtype=np.float32)
            embeddings.append(emb)
            valid_logs.append(log)
        except Exception as e:
            print(f"[get_similar_feedback] Skipping corrupted embedding: {e}")

    if not embeddings:
        print("[get_similar_feedback] No valid embeddings found.")
        return []

    # Convert to matrix and normalize for cosine similarity
    embeddings = np.vstack(embeddings)
    faiss.normalize_L2(embeddings)

    # Build FAISS index for inner product (which, with normalized vectors, is cosine similarity)
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    print("[get_similar_feedback] FAISS index built and embeddings added.")

    # Search top_k most similar feedbacks
    D, I = index.search(query_embedding.reshape(1, -1), top_k)
    # D: distances (similarities), I: indices

    print(f"[get_similar_feedback] Similarity scores: {D}")
    results = []
    for idx, score in zip(I[0], D[0]):
        if idx < 0 or score < threshold:
            continue
        log = valid_logs[idx]
        results.append((log, score))

    print(f"[get_similar_feedback] Returning top {len(results)} results.")
    return results