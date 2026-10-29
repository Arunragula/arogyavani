# app/services/llm_router.py
import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()


def get_model_chain() -> list[str]:
    chain_str = os.getenv(
        "GEMINI_MODEL_CHAIN",
        "gemini-3.6-flash,gemini-3.8-flash,gemini-2.5-flash,gemini-2.5-flash-lite,gemini-3-flash,gemini-3.1-flash-lite,gemini-3.5-flash-lite",
    )
    return [m.strip() for m in chain_str.split(",") if m.strip()]


def call_gemini_json_chain(system_prompt: str, user_prompt: str) -> dict:
    """
    Tries each free Gemini model in GEMINI_MODEL_CHAIN in order.
    Uses temperature=0.0 so medical outputs remain consistent and deterministic.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY is missing in your .env file.")

    client = genai.Client(api_key=api_key)
    models = get_model_chain()
    last_error = None

    for model_name in models:
        try:
            config_kwargs = {
                "system_instruction": system_prompt,
                "temperature": 0.0,  # Strict determinism for consistent medical results
                "response_mime_type": "application/json",
            }
            # Disable slow hidden thinking on 2.5 models for 2x faster responses
            if "2.5" in model_name:
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

            response = client.models.generate_content(
                model=model_name,
                contents=user_prompt,
                config=types.GenerateContentConfig(**config_kwargs),
            )
            return json.loads(response.text)

        except Exception as err:
            print(f"[LLM Router] Model '{model_name}' limit/error ({err}). Shifting to next model...")
            last_error = err
            continue

    raise RuntimeError(f"All Gemini models in chain failed. Last error: {last_error}")