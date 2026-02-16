from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import httpx

OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

@dataclass(frozen=True)
class CloudResult:
    text: str

def _extract_text_from_responses(data: dict) -> str:
    chunks: list[str] = []

    for item in data.get("output", []):
        # Common: {"type":"message","content":[{"type":"output_text","text":"..."}]}
        for part in item.get("content", []):
            t = part.get("text")
            if isinstance(t, str) and t.strip():
                chunks.append(t)

    # Fallback: sometimes APIs include other convenience fields
    if not chunks:
        maybe = data.get("output_text")
        if isinstance(maybe, str) and maybe.strip():
            chunks.append(maybe)

    return "\n".join(chunks).strip()

async def ask_openai_sanitized(prompt: str) -> Optional[CloudResult]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None

    if not prompt or not prompt.strip():
        return CloudResult(text="(Sanitized query was empty; cloud skipped.)")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": DEFAULT_MODEL,
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}],
            }
        ],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(f"{OPENAI_BASE_URL}/responses", headers=headers, json=payload)

        if r.status_code >= 400:
            # Log this string to your evidence logs
            err_body = r.text
            raise RuntimeError(f"OpenAI error {r.status_code}: {err_body}")

        data = r.json()

    out_text = _extract_text_from_responses(data)
    return CloudResult(text=out_text if out_text else "(No text returned; check payload/model or log response JSON.)")
