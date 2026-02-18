import sys
from pathlib import Path

# add sentiment src to path
ROOT = Path(__file__).resolve().parents[2]
SENTIMENT_SRC = ROOT / "apps" / "sentiment"
sys.path.insert(0, str(SENTIMENT_SRC))

import importlib.util

spec = importlib.util.spec_from_file_location(
    "sentiment_main", SENTIMENT_SRC / "main.py"
)
sentiment_main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sentiment_main)


class DummyLogger:
    def __init__(self):
        self.msg = None

    def info(self, msg):
        self.msg = msg


def test_main_logs_message(monkeypatch):
    dummy = DummyLogger()
    monkeypatch.setattr(sentiment_main, "logger", dummy)
    sentiment_main.main()
    assert dummy.msg == "Hello from sentiment!"
