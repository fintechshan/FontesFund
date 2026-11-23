"""Real WSGI process for tests/test_wsgi_serving.py.

The parent sets SKIP_CLOCKS, SKIP_AI, and the hold latches. This file does
not set them, and it does not connect to a broker.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dashboard.wsgi_app import serve

if __name__ == "__main__":
    serve()
