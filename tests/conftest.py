import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("JOBLIB_MULTIPROCESSING", "0")
os.environ.setdefault("JOBLIB_TEMP_FOLDER", tempfile.gettempdir())

ROOT = Path(__file__).resolve().parents[1]
paths = [
    ROOT / "apps" / "common" / "src",
    ROOT / "apps" / "ingestion" / "src",
    ROOT / "apps" / "scorer" / "src",
    ROOT / "apps" / "sentiment",
    ROOT / "apps" / "newswire" / "src",
]
for p in paths:
    sys.path.insert(0, str(p))
