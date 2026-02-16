import os
import uvicorn
from eurosec_ai.main import app

if __name__ == "__main__":
    host = os.getenv("EUROSEC_BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("EUROSEC_BACKEND_PORT", "48155"))
    uvicorn.run(app, host=host, port=port, log_level="info")
