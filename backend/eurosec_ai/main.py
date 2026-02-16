from __future__ import annotations

import os
from dotenv import load_dotenv

# ✅ UPDATED: robust .env loading for dev + packaged (PyInstaller) runs
import sys
from pathlib import Path

# Keep your original call (do not remove)
load_dotenv()

# ✅ ADDITION: also try loading .env from common packaged/dev locations
def _load_dotenv_robust() -> None:
    candidates = []

    # 1) Packaged binary location (PyInstaller): same folder as executable
    try:
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / ".env")
    except Exception:
        pass

    # 2) Current working directory (sometimes used in dev)
    try:
        candidates.append(Path(os.getcwd()) / ".env")
    except Exception:
        pass

    # 3) Backend project root (backend/.env) relative to this file
    # main.py likely at backend/eurosec_ai/main.py -> parents[1] = backend/
    try:
        candidates.append(Path(__file__).resolve().parents[1] / ".env")
    except Exception:
        pass

    for p in candidates:
        if p and p.exists():
            load_dotenv(p, override=False)
            # Optional debug (safe): shows where .env came from without printing secrets
            print(f"[dotenv] loaded from: {p}")
            return

    # Optional debug if nothing found
    print("[dotenv] .env not found in robust search; relying on environment variables only")

_load_dotenv_robust()


from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .logging_conf import setup_logging
from .orchestrator.orchestrator import Orchestrator
from .schemas.dtos import ChatRequest, ChatResponse

# ----------------------------
# Logging (GDPR-friendly)
# ----------------------------
setup_logging()

# ----------------------------
# App
# ----------------------------
app = FastAPI(title="EuroSec AI Backend", version="1.0.0")
orchestrator = Orchestrator()

# ----------------------------
# CORS
# - Dev: Vite ports
# - Prod Electron: "null" origin (file://)
# ----------------------------
DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "null",  # ✅ Electron prod: file:// origin often shows as "null"
]

# Optional: allow overriding via env (comma-separated)
# Example:
#   export EUROSEC_DEV_ORIGINS="http://localhost:9999,http://127.0.0.1:9999"
extra_origins = os.getenv("EUROSEC_DEV_ORIGINS", "").strip()
if extra_origins:
    DEV_ORIGINS.extend([o.strip() for o in extra_origins.split(",") if o.strip()])

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],  # includes OPTIONS (preflight)
    allow_headers=["*"],  # includes Content-Type
)

# ----------------------------
# Routes
# ----------------------------
@app.get("/")
def root():
    return {
        "message": "EuroSec AI backend is running.",
        "try": ["/health", "/docs", "/chat"],
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/routes")
def routes():
    
    return [
        {
            "path": r.path,
            "methods": sorted(list(getattr(r, "methods", []))),
        }
        for r in app.router.routes
    ]


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    
    return orchestrator.process(req)
