from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..schemas.dtos import ChatRequest, ChatResponse, Evidence
from .intent import classify_intent
from .sensitivity import detect_sensitive
from .extract_terms import extract_public_terms, to_dict
from .sanitize import build_cloud_query

from ..local_layer.pipeline import run_local_pipeline
from ..cloud_layer.openai_client import ask_openai_sanitized


@dataclass(frozen=True)
class RoutePlan:
    route: str  # "local" or "cloud"
    cloud_query: Optional[str]


# -------------------------
# Cloud enrichment helpers
# -------------------------
ROLE_HINT_RE = re.compile(
    r"\b(for|as|into)\s+(a\s+)?(?P<role>[a-zA-Z][a-zA-Z0-9 \-/]{2,})\b",
    re.IGNORECASE,
)

COMMON_ROLE_WORDS = {
    "role", "position", "job", "cv", "resume", "bullet", "bullets", "rewrite",
    "improve", "tailor", "summary", "summarize",
}

def build_role_enrichment_prompt(user_text: str) -> Optional[str]:
    """
    Returns a *sanitized*, general-knowledge prompt (no doc content).
    Example: "Give concise cybersecurity resume keywords + responsibilities + tools."
    """
    t = (user_text or "").strip()
    if not t:
        return None

    # If user explicitly asks for role tailoring, try to extract role
    role = None
    m = ROLE_HINT_RE.search(t)
    if m:
        role = (m.group("role") or "").strip()

    # Lightweight fallback: if user says "cybersecurity role" etc.
    if role is None:
        # try a small list of known role keywords
        if "cyber" in t.lower():
            role = "cybersecurity"
        elif "data analyst" in t.lower():
            role = "data analyst"
        elif "backend" in t.lower():
            role = "backend developer"
        elif "devops" in t.lower():
            role = "devops engineer"

    if role is None:
        return None

    # Keep it general. No personal data. No document text.
    return (
        "Provide a concise, general guide for a resume rewrite for the role: "
        f"{role}. Include:\n"
        "- 10–15 role-aligned keywords/skills\n"
        "- 6–10 responsibilities phrased as resume bullets\n"
        "- Common tools/tech (if applicable)\n"
        "Do NOT ask for personal details. Keep output generic."
    )


def merge_role_knowledge_into_output(local_text: str, cloud_text: str) -> str:
    """
    Merge happens locally (safe). Keep the merge minimal to avoid bloating output.
    """
    lt = (local_text or "").rstrip()
    ct = (cloud_text or "").strip()
    if not ct:
        return lt

    return (
        lt
        + "\n\n"
        + "## General role-aligned keywords (from Internet Layer)\n"
        + ct
        + "\n"
    )


async def _cloud_call(prompt: str) -> Optional[str]:
    res = await ask_openai_sanitized(prompt)
    return res.text if res else None


# -------------------------
# Orchestrator
# -------------------------
class Orchestrator:
    def plan(
        self, req: ChatRequest
    ) -> Tuple[RoutePlan, Dict[str, object], bool, List[str], str, str]:
        """
        Returns:
        - plan: where we intend to route (local/cloud)
        - extracted_terms: public terms extracted from user prompt
        - sensitive: whether user prompt itself looks sensitive
        - reasons: sensitivity reasons
        - intent: intent classifier output
        - sanitized_cloud_query: what we'd send to cloud if needed
        """
        intent_res = classify_intent(req.user_text)
        sens = detect_sensitive(req.user_text)
        terms = extract_public_terms(req.user_text)

        sanitized = build_cloud_query(
            user_text=req.user_text,
            roles=terms.roles,
            topics=terms.topics,
            intent=intent_res.intent,
        )

        # Strict routing:
        # - If sensitive OR cloud not allowed => local
        # - Else => cloud allowed (sanitized prompt only)
        if sens.sensitive or not req.allow_cloud:
            plan = RoutePlan(route="local", cloud_query=None)
        else:
            plan = RoutePlan(route="cloud", cloud_query=sanitized.cloud_query)

        return plan, to_dict(terms), sens.sensitive, sens.reasons, intent_res.intent, sanitized.cloud_query

    def process(self, req: ChatRequest) -> ChatResponse:
        plan, extracted_terms, user_sensitive, reasons, intent, sanitized_cloud_query = self.plan(req)

        evidence: List[Evidence] = []
        evidence.append(Evidence(source="orchestrator", note=f"intent={intent}"))
        if reasons:
            evidence.append(Evidence(source="sensitivity_detector", note=",".join(reasons)))

        used_cloud = False
        cloud_text: Optional[str] = None
        enrichment_prompt: Optional[str] = None

        # ✅ Decide whether we want internet enrichment
        # Summarize stays pure local (privacy-first)
        wants_enrichment = (
            req.allow_cloud
            and intent in {"rewrite", "improve", "tailor", "bulletize", "general_question"}
            and intent != "summarize"
        )

        # ✅ If we want enrichment, do it BEFORE local enhancement so we can inject public_knowledge
        if wants_enrichment:
            enrichment_prompt = build_role_enrichment_prompt(req.user_text)

            # If no clear role/goal was detected, we still can use sanitized_cloud_query
            prompt_to_send = enrichment_prompt or sanitized_cloud_query

            if prompt_to_send:
                cloud_text = asyncio.run(_cloud_call(prompt_to_send))
                if cloud_text is None:
                    evidence.append(Evidence(source="cloud", note="OPENAI_API_KEY missing; cloud skipped"))
                    used_cloud = False
                    cloud_text = None
                else:
                    used_cloud = True
                    evidence.append(Evidence(source="cloud", note="sanitized_enrichment_used"))

        # --- Always run local pipeline (offline) ---
        # If we got safe cloud knowledge, inject it into template enhancement (merge remains local)
        local_result = run_local_pipeline(
            req=req,
            intent=intent,
            public_knowledge=cloud_text,  # ✅ optional
        )
        evidence.extend(local_result.evidence)

        # Final: keep local output as primary
        final_text = local_result.text

        # If local output didn't already use the public_knowledge (depends on your template_enhance),
        # we still append the cloud block for transparency.
        # (This also helps you demonstrate “sanitized cloud query works” in your thesis.)
        if cloud_text:
            final_text = merge_role_knowledge_into_output(final_text, cloud_text)

        return ChatResponse(
            final_text=final_text,
            used_cloud=used_cloud,
            sensitive_detected=local_result.sensitive_detected or user_sensitive,
            sanitized_cloud_query=(enrichment_prompt or sanitized_cloud_query) if req.allow_cloud else None,
            extracted_public_terms=extracted_terms,
            evidence=evidence,
            route=("cloud" if used_cloud else plan.route),
        )
