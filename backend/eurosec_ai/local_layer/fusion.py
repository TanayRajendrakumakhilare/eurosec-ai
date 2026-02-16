from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class FusionResult:
    final_text: str

def fuse(local_text: str, cloud_text: Optional[str]) -> FusionResult:
    if cloud_text:
        combined = (
            "=== Local Result (private-safe) ===\n"
            f"{local_text}\n\n"
            "=== Public Cloud Knowledge (sanitized) ===\n"
            f"{cloud_text}\n"
        )
        return FusionResult(final_text=combined)

    return FusionResult(final_text=local_text)
