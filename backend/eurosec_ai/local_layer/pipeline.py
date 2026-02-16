from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional
import os
import re

from ..schemas.dtos import Evidence, ChatRequest
from .permissions import normalize_roots
from .file_search import search_files
from .file_extract import extract_text
from .text_clean import clean_text
from .template_enhance import enhance_with_context
from ..orchestrator.sanitize import redact
from .summarizer import summarize_document


@dataclass(frozen=True)
class LocalPipelineResult:
    text: str
    evidence: List[Evidence]
    sensitive_detected: bool = False


# -------------------------
# Helpers
# -------------------------
def _tokenize(q: str) -> List[str]:
    q = (q or "").lower().strip()
    return [t for t in re.split(r"[^a-z0-9]+", q) if len(t) >= 2]


def _is_under_roots(path: str, roots: Iterable[str]) -> bool:
    p = os.path.abspath(path)
    for r in roots:
        rr = os.path.abspath(r)
        if p == rr:
            return True
        if p.startswith(rr + os.sep):
            return True
    return False


def _looks_like_explicit_file_query(text: str) -> bool:
    # supports: file:"X.pdf" or file:X.pdf or file: X.pdf
    return bool(re.search(r'\bfile\s*:\s*(".*?"|\S+)', text or "", flags=re.IGNORECASE))


_SMALLTALK_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|thanks|thank you|ok|okay|cool|nice|good|great|bye|goodbye)\s*[!.]*\s*$",
    re.IGNORECASE,
)


# -------------------------
# Main pipeline
# -------------------------
def run_local_pipeline(
    req: ChatRequest,
    intent: str,
    *,
    public_knowledge: Optional[str] = None,  # ✅ sanitized cloud knowledge (optional)
) -> LocalPipelineResult:
    ev: List[Evidence] = []

    user_text = (req.user_text or "").strip()
    has_preferred = bool(req.preferred_files)
    explicit_file = _looks_like_explicit_file_query(user_text)

    # Only these intents truly require file access:
    needs_files = intent in {"summarize", "rewrite", "improve", "tailor", "bulletize", "file_search"} or has_preferred or explicit_file

    # ✅ If it's smalltalk/general and no file is selected → DO NOT require workspace
    if not needs_files:
        if _SMALLTALK_RE.match(user_text):
            return LocalPipelineResult(
                text="Hi! 👋 How can I help you? If you want a document summary, select a file and ask: “Summarize this file”.",
                evidence=[Evidence(source="local", note="smalltalk_no_file")],
                sensitive_detected=False,
            )
        return LocalPipelineResult(
            text="I can answer general questions (and summarize/rewrite files if you select a workspace + file). What do you want to do?",
            evidence=[Evidence(source="local", note="general_no_file")],
            sensitive_detected=False,
        )

    # ✅ For file operations, NOW we need workspace permissions
    perm = normalize_roots(req.workspace_dirs)
    if not perm.allowed_roots:
        ev.append(Evidence(source="permissions", note="no_workspace_dirs_provided"))
        return LocalPipelineResult(
            text="Please choose workspace folders (local permissions) so I can search your files offline.",
            evidence=ev,
            sensitive_detected=False,
        )
    ev.append(Evidence(source="permissions", note=f"allowed_roots={len(perm.allowed_roots)}"))

    # 1) If UI selected a file, FORCE it
    hits = None
    if req.preferred_files:
        preferred_path = req.preferred_files[0]
        if not _is_under_roots(preferred_path, perm.allowed_roots):
            ev.append(Evidence(source="permissions", path=preferred_path, note="preferred_file_outside_allowed_roots"))
            return LocalPipelineResult(
                text="That selected file is outside your approved workspace folders. Please add its folder as a workspace.",
                evidence=ev,
                sensitive_detected=False,
            )

        class _Hit:
            def __init__(self, path: str, reason: str, score: float):
                self.path = path
                self.reason = reason
                self.score = score

        hits = [_Hit(preferred_path, "preferred_file", 9999.0)]

    # 2) Otherwise search files
    if hits is None:
        hits = search_files(
            query=req.user_text,
            allowed_roots=perm.allowed_roots,
            preferred_files=req.preferred_files,
            limit=5,
        )

    if not hits:
        ev.append(Evidence(source="file_search", note="no_files_found"))
        return LocalPipelineResult(
            text="I couldn’t find relevant files in your approved folders. Try different keywords or add folders.",
            evidence=ev,
            sensitive_detected=False,
        )

    tokens = _tokenize(req.user_text)
    best = None  # (overlap_score, path, raw_text, cleaned_text, file_type)

    # 3) Extract + choose best hit
    for h in hits:
        score = float(getattr(h, "score", 0.0))
        reason = str(getattr(h, "reason", "unknown"))
        ev.append(Evidence(source="file_search", path=h.path, note=f"{reason} score={score:.2f}"))

        ex = extract_text(h.path)
        raw_text = (ex.text or "").strip()
        ev.append(Evidence(source="file_extract", path=h.path, note=f"type={ex.file_type} chars={len(raw_text)}"))

        if not raw_text:
            continue

        cleaned = clean_text(raw_text)
        cleaned_text = (cleaned.cleaned or "").strip()

        overlap = sum(1 for t in tokens if t in raw_text.lower())
        if best is None or overlap > best[0]:
            best = (overlap, h.path, raw_text, cleaned_text, ex.file_type)

        if reason == "preferred_file":
            break

    if not best:
        return LocalPipelineResult(
            text="Files were found, but I couldn’t extract readable text. (Try TXT/DOCX or text-based PDFs.)",
            evidence=ev,
            sensitive_detected=False,
        )

    overlap, chosen_path, raw_text, cleaned_text, file_type = best
    ev.append(Evidence(source="file_choice", path=chosen_path, note=f"content_overlap={overlap}"))

    # 4) Redact before using any document content
    safe_raw = redact(raw_text)

    doc_sensitive = (safe_raw != raw_text)
    if doc_sensitive:
        ev.append(Evidence(source="sensitivity_detector", path=chosen_path, note="pii_found_in_document"))

    # 5) Summarize (local-only)
    if intent == "summarize":
        summary = summarize_document(safe_raw, detail_level="full")

        executive_bullets = getattr(summary, "executive_bullets", []) or []
        coverage_lines = getattr(summary, "coverage_lines", []) or []
        short = getattr(summary, "short", "") or ""
        stats = getattr(summary, "stats", "") or ""
        warnings = getattr(summary, "warnings", []) or []
        section_bullets = getattr(summary, "section_bullets", {}) or {}

        out_parts: List[str] = []
        out_parts.append("Offline summary (local-only):\n")
        out_parts.append(f"Source file:\n[{file_type.upper()}] {chosen_path}\n")

        if warnings:
            out_parts.append("Warnings:")
            for w in warnings[:6]:
                out_parts.append(f"- {w}")
            out_parts.append("")

        out_parts.append("Executive summary (bullets):")
        out_parts.append("\n".join(executive_bullets) if executive_bullets else "- (no highlights found)")
        out_parts.append("")

        if isinstance(section_bullets, dict) and section_bullets:
            out_parts.append("Section highlights:")
            for sec, bs in list(section_bullets.items())[:10]:
                out_parts.append(f"## {sec}")
                for b in (bs or [])[:4]:
                    out_parts.append(b)
            out_parts.append("")

        out_parts.append("Document coverage (chunk-by-chunk):")
        out_parts.append("\n".join(coverage_lines) if coverage_lines else "(no chunk summaries)")
        out_parts.append("")
        out_parts.append("Short summary:")
        out_parts.append(short or "(not enough text)")
        out_parts.append("")
        out_parts.append("Coverage:")
        out_parts.append(stats or "(no stats)")
        out_parts.append("")

        return LocalPipelineResult(text="\n".join(out_parts), evidence=ev, sensitive_detected=doc_sensitive)

    # 6) Rewrite / Improve / Bulletize / Tailor (Template-Based Enhancement Engine)
    if intent in {"rewrite", "improve", "tailor", "bulletize"}:
        # ✅ Use redacted RAW to preserve layout (CVs are layout-heavy)
        tbe = enhance_with_context(
            intent=intent,
            user_text=req.user_text,
            context_excerpt=safe_raw,
            public_knowledge=public_knowledge,  # ✅ sanitized cloud knowledge can be injected here
        )
        meta = tbe.meta or {}
        ev.append(
            Evidence(
                source="tbe",
                path=chosen_path,
                note=f"doc_type={meta.get('doc_type')} role={meta.get('role')} bullets={meta.get('bullets')} keywords={meta.get('keywords')}",
            )
        )

        out = f"Source file:\n[{file_type.upper()}] {chosen_path}\n\n{tbe.text}"
        return LocalPipelineResult(text=out, evidence=ev, sensitive_detected=doc_sensitive)

    # 7) Other intents (keep previous behavior)
    context = cleaned_text if len(cleaned_text) >= 200 else safe_raw
    enh = enhance_with_context(intent=intent, user_text=req.user_text, context_excerpt=context).text
    enh = f"Source file:\n[{file_type.upper()}] {chosen_path}\n\n{enh}"
    return LocalPipelineResult(text=enh, evidence=ev, sensitive_detected=doc_sensitive)
