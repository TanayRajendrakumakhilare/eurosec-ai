from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List


@dataclass(frozen=True)
class PermissionResult:
    allowed_roots: List[Path]


def normalize_roots(workspace_dirs: Iterable[str]) -> PermissionResult:
    roots: List[Path] = []
    for d in workspace_dirs:
        p = Path(d).expanduser().resolve()
        if p.exists() and p.is_dir():
            roots.append(p)
    return PermissionResult(allowed_roots=roots)


def is_path_allowed(path: Path, allowed_roots: List[Path]) -> bool:
    try:
        rp = path.expanduser().resolve()
    except Exception:
        return False
    for root in allowed_roots:
        try:
            rp.relative_to(root)
            return True
        except Exception:
            continue
    return False
