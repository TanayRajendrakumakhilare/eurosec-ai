from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple
import os
import re


# Skip noisy directories that destroy relevance & performance
IGNORE_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".next",
    "__pycache__",
    ".venv",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
}

# Keep search focused on docs (add more if you want)
ALLOWED_EXTS = {".pdf", ".docx", ".txt", ".md", ".xlsx", ".csv"}


@dataclass(frozen=True)
class FileHit:
    path: str
    reason: str
    score: float


def _tokenize(q: str) -> List[str]:
    q = (q or "").lower().strip()
    return [t for t in re.split(r"[^a-z0-9]+", q) if len(t) >= 2]


def _extract_file_directive(q: str) -> Optional[str]:
    """
    Supports:
      file:"My Doc.pdf"
      file:MyDoc.pdf
      file: MyDoc.pdf
    Returns the raw filename string (not a path).
    """
    if not q:
        return None
    m = re.search(r'\bfile\s*:\s*("([^"]+)"|(\S+))', q, flags=re.IGNORECASE)
    if not m:
        return None
    return (m.group(2) or m.group(3) or "").strip() or None


def _is_under_roots(path: str, allowed_roots: Iterable[str]) -> bool:
    p = os.path.abspath(path)
    for r in allowed_roots:
        rr = os.path.abspath(r)
        if p == rr:
            return True
        if p.startswith(rr + os.sep):
            return True
    return False


def _walk_files(allowed_roots: List[str]) -> Iterable[str]:
    """
    Yields file paths under allowed_roots, pruning IGNORE_DIRS and hidden dirs.
    """
    for root in allowed_roots:
        root = os.path.abspath(root)
        if not os.path.isdir(root):
            continue

        for base, dirs, files in os.walk(root, topdown=True, followlinks=False):
            # ✅ PRUNE DIRS IN-PLACE (the important part)
            dirs[:] = [
                d
                for d in dirs
                if d not in IGNORE_DIRS and not d.startswith(".")
            ]

            for fn in files:
                # skip hidden files
                if fn.startswith("."):
                    continue

                ext = os.path.splitext(fn)[1].lower()
                if ext and ext not in ALLOWED_EXTS:
                    continue

                yield os.path.join(base, fn)


def _score_filename_match(tokens: List[str], filename: str) -> float:
    """
    Simple scoring purely on filename.
    """
    low = filename.lower()
    if not tokens:
        return 0.0

    score = 0.0
    for t in tokens:
        if t in low:
            score += 2.0

    # Bonus if ALL tokens appear
    if score > 0 and all(t in low for t in tokens):
        score += 3.0

    return score


def _find_by_exact_basename(allowed_roots: List[str], wanted_name: str) -> Optional[str]:
    """
    Look for exact basename match (case-insensitive) inside allowed roots.
    Returns the first match found.
    """
    wanted_low = wanted_name.lower()

    for p in _walk_files(allowed_roots):
        base = os.path.basename(p).lower()
        if base == wanted_low:
            return p
    return None


def search_files(
    query: str,
    allowed_roots: List[str],
    preferred_files: Optional[List[str]] = None,
    limit: int = 5,
) -> List[FileHit]:
    """
    File search is NAME-based (not content-based).
    Content extraction & summarization happens later in pipeline.py.
    """
    preferred_files = preferred_files or []

    # 0) If preferred file(s) given, validate they are under roots and return top hit(s)
    # (Your pipeline already forces preferred_files; this is an extra safety net.)
    preferred_hits: List[FileHit] = []
    for pf in preferred_files:
        if pf and os.path.isfile(pf) and _is_under_roots(pf, allowed_roots):
            preferred_hits.append(FileHit(path=pf, reason="preferred_file", score=9999.0))

    if preferred_hits:
        return preferred_hits[:limit]

    # 1) If user used file:"X.pdf" directive, force exact match
    wanted = _extract_file_directive(query)
    if wanted:
        exact = _find_by_exact_basename(allowed_roots, wanted)
        if exact:
            return [FileHit(path=exact, reason="explicit_filename_exact_match", score=9998.0)]

        # If not exact, continue with fuzzy scoring, but boost those containing the wanted string
        tokens = _tokenize(wanted)
    else:
        tokens = _tokenize(query)

    # 2) Walk allowed roots and score filenames
    hits: List[Tuple[float, str, str]] = []  # (score, path, reason)

    for p in _walk_files(allowed_roots):
        fn = os.path.basename(p)
        s = _score_filename_match(tokens, fn)

        if wanted and wanted.lower() in fn.lower():
            s += 5.0  # strong boost for containing requested filename fragment

        if s <= 0:
            continue

        hits.append((s, p, "filename_match"))

    # 3) Sort descending by score and return top results
    hits.sort(key=lambda x: x[0], reverse=True)

    out: List[FileHit] = []
    for s, p, reason in hits[: max(1, limit)]:
        out.append(FileHit(path=p, reason=reason, score=float(s)))

    return out
