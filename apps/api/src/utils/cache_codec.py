from __future__ import annotations

import base64
import gzip
import json
from typing import Any


def serialize_compressed_json(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, default=str, separators=(",", ":")).encode("utf-8")
    compressed = gzip.compress(raw)
    return base64.b64encode(compressed).decode("ascii")


def deserialize_compressed_json(data: str) -> dict[str, Any]:
    try:
        decoded = base64.b64decode(data.encode("ascii"))
        decompressed = gzip.decompress(decoded)
        return json.loads(decompressed.decode("utf-8"))
    except Exception:
        # Fall back to plain JSON for legacy/non-compressed entries.
        return json.loads(data)
