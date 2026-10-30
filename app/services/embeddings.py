# app/services/embeddings.py
import os
import hashlib
import numpy as np
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

VECTOR_DIM = 768


def generate_local_embedding(text: str) -> list[float]:
    if not text or not text.strip():
        return [0.0] * VECTOR_DIM

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key:
        try:
            client = genai.Client(api_key=api_key)
            res = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text[:8000],
                config=types.EmbedContentConfig(output_dimensionality=VECTOR_DIM),
            )
            vec = np.array(res.embeddings[0].values, dtype=float)
            norm = np.linalg.norm(vec)
            return (vec / norm).tolist() if norm > 0 else vec.tolist()
        except Exception:
            pass

    # Deterministic hashlib fallback (consistent across server restarts)
    vec = np.zeros(VECTOR_DIM, dtype=float)
    for word in text.lower().split():
        digest = int(hashlib.md5(word.encode("utf-8")).hexdigest()[:8], 16)
        vec[digest % VECTOR_DIM] += 1.0
    norm = np.linalg.norm(vec)
    return (vec / norm).tolist() if norm > 0 else vec.tolist()