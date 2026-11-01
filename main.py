import sys
from pathlib import Path

# Add src to Python path so occasio package is importable
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from occasio.api.app import create_app  # noqa: E402

app = create_app()
