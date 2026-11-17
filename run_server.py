import os
import sys
from pathlib import Path

import uvicorn

# Run from the project root so the `backend` package resolves, regardless of the
# directory this script is launched from.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8001"))
    print(f"Starting Boomerang Backend from {ROOT} on http://localhost:{port}...")

    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )
