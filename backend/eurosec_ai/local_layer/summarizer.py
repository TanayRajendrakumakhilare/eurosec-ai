from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
import math
import re


def _load_nlp():
    try:
        import spacy  # type: ignore
        return spacy.load("en_core_web_sm")
    except Exception:
        return None


NLP = _load_nlp()

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "to", "of", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "being", "this", "that", "these", "those", "it", "its",
    "as", "at", "by", "from", "into", "about", "over", "under", "we", "you", "i", "they", "he", "she",
    "my", "your", "our", "their", "me", "him", "her", "them",
}

WORD_RE = re.compile(r"\b[a-zA-Z][a-zA-Z0-9_+\-./#]{1,}\b")
LINE_SPLIT_RE = re.compile(r"\r?\n+")
SENT_SPLIT_FALLBACK = re.compile(r"(?<=[.!?])\s+|\n+")
BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*•\u2022]|➢|›|»)\s+")
HEADING_RE = re.compile(r"^\s*([A-Z][A-Z0-9 &/\-]{3,}|[A-Z][a-zA-Z ]{2,})\s*:?\s*$")


@dataclass(frozen=True)
class Summary:
    """
    IMPORTANT: This object is also used by pipeline.py.

    We keep:
    - executive_bullets (global highlights)
    - section_bullets (per-section highlights, when headings exist)
    - coverage_lines (chunk-by-chunk coverage)

    And we ALSO expose compatibility aliases:
    - detailed_blocks  (alias for coverage_lines)
    - bullets          (alias for executive_bullets)
    """
    executive_bullets: List[str]
    section_bullets: Dict[str, List[str]]
    coverage_lines: List[str]
    short: str
    stats: str
    warnings: List[str]

    @property
    def detailed_blocks(self) -> List[str]:
        return self.coverage_lines

    @property
    def bullets(self) -> List[str]:
        return self.executive_bullets


# ----------------------------
# text utilities
# ----------------------------
def _norm_ws(s: str) -> str:
    return " ".join((s or "").replace("\u2022", " ").replace("•", " ").split()).strip()


def _tokens(text: str) -> List[str]:
    words = [w.lower() for w in WORD_RE.findall(text or "")]
    return [w for w in words if w not in STOPWORDS and len(w) >= 2]


def _sentences(text: str) -> List[str]:
    """
    Sentence splitter that works for:
    - normal prose
    - PDFs with newlines
    - CVs / bullet lists (fallback keeps shorter segments than before)
    """
    t = (text or "").strip()
    if not t:
        return []

    if NLP is not None:
        try:
            doc = NLP(t)
            sents = [s.text.strip() for s in doc.sents if s.text.strip()]
            if sents:
                return sents
        except Exception:
            pass

    parts = SENT_SPLIT_FALLBACK.split(t)
    out: List[str] = []
    for p in parts:
        p = _norm_ws(p)
        # Lower threshold helps CV/bullet content. Keep it not-too-small to avoid noise.
        if len(p) >= 14:
            if not p.endswith((".", "!", "?")):
                p += "."
            out.append(p)
    return out


def _line_is_heading(line: str) -> bool:
    s = (line or "").strip()
    if not s:
        return False
    if BULLET_PREFIX_RE.match(s):
        return False
    if len(s) > 70:
        return False
    return HEADING_RE.match(s) is not None


def _split_into_sections(text: str) -> Dict[str, str]:
    """
    Works for any doc:
    - If headings exist -> section map
    - Otherwise -> {"Document": text}
    """
    raw = (text or "").strip()
    if not raw:
        return {}

    lines = [l.rstrip() for l in LINE_SPLIT_RE.split(raw) if l.strip()]
    if not lines:
        return {"Document": raw}

    sections: Dict[str, List[str]] = {}
    current = "Document"
    sections[current] = []

    heading_count = 0
    for line in lines:
        if _line_is_heading(line):
            heading_count += 1
            current = line.strip().rstrip(":").title()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)

    # If almost no headings, treat as generic doc
    if heading_count < 2:
        return {"Document": raw}

    joined = {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}
    return joined if joined else {"Document": raw}


def _build_idf(items_tokens: List[List[str]]) -> Dict[str, float]:
    df: Dict[str, int] = {}
    for toks in items_tokens:
        for w in set(toks):
            df[w] = df.get(w, 0) + 1
    n = max(1, len(items_tokens))
    return {w: math.log((n + 1) / (c + 1)) + 1.0 for w, c in df.items()}


def _score_sentence(sent_toks: List[str], idf: Dict[str, float], position: float) -> float:
    if not sent_toks:
        return 0.0

    tf: Dict[str, int] = {}
    for w in sent_toks:
        tf[w] = tf.get(w, 0) + 1

    score = 0.0
    for w, c in tf.items():
        score += (1.0 + math.log(c)) * idf.get(w, 1.0)

    score /= max(1e-9, math.sqrt(len(sent_toks)))

    # slight preference for earlier sentences
    score *= (1.10 - 0.25 * position)

    # penalize “tool dump” lines (still works for non-CV docs)
    if len(sent_toks) > 14:
        # if the content looks like a long comma-separated list, reduce a bit
        score *= 0.90

    return score


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def _clip(s: str, n: int) -> str:
    s = _norm_ws(s)
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


def _chunk_by_words(text: str, words_per_chunk: int, overlap_words: int) -> List[str]:
    ws = (text or "").split()
    if not ws:
        return []

    if words_per_chunk <= 0:
        return [" ".join(ws)]

    out: List[str] = []
    i = 0
    step = max(1, words_per_chunk - max(0, overlap_words))
    while i < len(ws):
        out.append(" ".join(ws[i:i + words_per_chunk]))
        i += step
    return out


def _detect_doc_style(text: str) -> str:
    """
    Heuristic:
    - If many headings -> 'sectioned'
    - If mostly bullet lines -> 'list-heavy'
    - Else -> 'generic'
    """
    raw = (text or "").strip()
    if not raw:
        return "generic"
    lines = [l.strip() for l in LINE_SPLIT_RE.split(raw) if l.strip()]
    if not lines:
        return "generic"

    heading_cnt = sum(1 for l in lines if _line_is_heading(l))
    bullet_cnt = sum(1 for l in lines if BULLET_PREFIX_RE.match(l))
    ratio_bullets = bullet_cnt / max(1, len(lines))

    if heading_cnt >= 3:
        return "sectioned"
    if ratio_bullets >= 0.35:
        return "list-heavy"
    return "generic"


def _line_sentences(text: str) -> List[str]:
    """
    For list-heavy PDFs (CVs), line-based "sentences" often cover content better than punctuation splitting.
    """
    raw = (text or "").strip()
    if not raw:
        return []

    lines = [l.strip() for l in LINE_SPLIT_RE.split(raw) if l.strip()]
    out: List[str] = []

    for ln in lines:
        ln = BULLET_PREFIX_RE.sub("", ln).strip()
        ln = _norm_ws(ln)
        if len(ln) < 18:
            continue
        if not ln.endswith((".", "!", "?")):
            ln += "."
        out.append(ln)

    return out


def summarize_document(text: str, detail_level: str = "full") -> Summary:
    raw = (text or "").strip()
    warnings: List[str] = []

    if not raw:
        return Summary([], {}, [], "", "empty_text", ["No text to summarize."])

    total_words = len(raw.split())
    total_chars = len(raw)

    # transparency: extraction completeness
    if total_chars < 1200 or total_words < 200:
        warnings.append(
            "Extracted text looks short. If the document is scanned or layout-heavy, OCR may be needed for full coverage."
        )

    style = _detect_doc_style(raw)
    sections = _split_into_sections(raw)

    # Build sentence pool (mix sentence + line extraction for list-heavy)
    sent_meta: List[Tuple[str, str]] = []

    for sec, sec_text in sections.items():
        sents = _sentences(sec_text)
        sent_meta.extend((sec, s) for s in sents)

        # For list-heavy docs, add line-based candidates too
        if style == "list-heavy":
            line_sents = _line_sentences(sec_text)
            sent_meta.extend((sec, s) for s in line_sents)

    # Dedup sentence pool (keep order)
    seen_norm = set()
    deduped: List[Tuple[str, str]] = []
    for sec, s in sent_meta:
        key = _norm_ws(s).lower()
        if key in seen_norm:
            continue
        seen_norm.add(key)
        deduped.append((sec, s))
    sent_meta = deduped

    if not sent_meta:
        return Summary([], {}, [], "", f"words={total_words} chars={total_chars}", warnings + ["No sentences detected."])

    sent_tokens = [_tokens(s) for _, s in sent_meta]
    idf = _build_idf(sent_tokens)

    scored: List[Tuple[float, int]] = []
    n = len(sent_meta)
    for i, (_, _) in enumerate(sent_meta):
        toks = sent_tokens[i]
        pos = i / max(1, n - 1)
        sc = _score_sentence(toks, idf, pos)

        # for sectioned docs, slightly boost non-“Document” sections
        if style == "sectioned" and sent_meta[i][0] != "Document":
            sc *= 1.08

        scored.append((sc, i))

    scored.sort(reverse=True, key=lambda x: x[0])

    # Executive bullets (global highlights, non-redundant)
    exec_target = 10 if detail_level == "full" else 6
    exec_bullets: List[str] = []
    used_sets: List[set[str]] = []

    for _, idx in scored:
        if len(exec_bullets) >= exec_target:
            break
        toks_set = set(sent_tokens[idx])
        if not toks_set:
            continue
        if any(_jaccard(toks_set, u) > 0.45 for u in used_sets):
            continue
        exec_bullets.append(f"- {_clip(sent_meta[idx][1], 220)}")
        used_sets.append(toks_set)

    # If we somehow got none (rare), fallback to strongest non-empty lines
    if not exec_bullets:
        for sec, s in sent_meta[: min(12, len(sent_meta))]:
            s = _clip(s, 220)
            if len(s) >= 30:
                exec_bullets.append(f"- {s}")
            if len(exec_bullets) >= min(exec_target, 6):
                break

    short = " ".join(_clip(b[2:], 120) for b in exec_bullets[:3])
    short = _clip(short, 360)

    # Section bullets (only meaningful if actually sectioned)
    section_bullets: Dict[str, List[str]] = {}
    if style == "sectioned":
        by_sec: Dict[str, List[int]] = {}
        for _, idx in scored:
            sec = sent_meta[idx][0]
            by_sec.setdefault(sec, []).append(idx)

        per_sec_target = 3 if detail_level == "full" else 2
        for sec, idxs in by_sec.items():
            picks: List[str] = []
            sec_used: List[set[str]] = []
            for idx in idxs:
                if len(picks) >= per_sec_target:
                    break
                toks_set = set(sent_tokens[idx])
                if not toks_set:
                    continue
                if any(_jaccard(toks_set, u) > 0.55 for u in sec_used):
                    continue
                picks.append(f"- {_clip(sent_meta[idx][1], 230)}")
                sec_used.append(toks_set)
            if picks:
                section_bullets[sec] = picks

    # Coverage: chunk-by-chunk (1 best sentence per chunk, avoids exec repetition but still ensures coverage)
    words_per_chunk = 260 if detail_level == "full" else 380
    overlap_words = 70 if detail_level == "full" else 40

    chunks = _chunk_by_words(raw, words_per_chunk=words_per_chunk, overlap_words=overlap_words)

    max_chunks = 14 if detail_level == "full" else 8
    if len(chunks) > max_chunks:
        idxs = [round(i * (len(chunks) - 1) / (max_chunks - 1)) for i in range(max_chunks)]
        chunks = [chunks[i] for i in idxs]

    coverage_lines: List[str] = []
    avoid_sets: List[set[str]] = [set(u) for u in used_sets]

    for ci, chunk in enumerate(chunks, start=1):
        sents = _sentences(chunk)
        if style == "list-heavy":
            sents = sents + _line_sentences(chunk)

        best_sent = None
        best_score = -1.0

        # Pass 1: try to avoid repeating executive bullets
        for s in sents:
            toks = _tokens(s)
            if not toks:
                continue
            toks_set = set(toks)
            if any(_jaccard(toks_set, u) > 0.60 for u in avoid_sets):
                continue
            sc = _score_sentence(toks, idf, position=0.35)
            if sc > best_score:
                best_score = sc
                best_sent = s

        # Pass 2 (fallback): if everything was filtered out, just pick best available
        if best_sent is None:
            for s in sents:
                toks = _tokens(s)
                if not toks:
                    continue
                sc = _score_sentence(toks, idf, position=0.35)
                if sc > best_score:
                    best_score = sc
                    best_sent = s

        if best_sent:
            coverage_lines.append(f"Chunk {ci}: {_clip(best_sent, 260)}")
            avoid_sets.append(set(_tokens(best_sent)))

    stats = f"words={total_words} chars={total_chars} style={style} sections={len(sections)} chunks={len(chunks)} detail={detail_level}"
    if not coverage_lines:
        warnings.append("Could not produce chunk coverage lines (document may be very short or extremely list-heavy).")

    return Summary(
        executive_bullets=exec_bullets,
        section_bullets=section_bullets,
        coverage_lines=coverage_lines,
        short=short,
        stats=stats,
        warnings=warnings,
    )
