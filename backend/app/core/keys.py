"""Redis key and stream names (docs/ARCHITECTURE.md "Data flow and Redis naming")."""

STREAM_STATUS = "desk:stream:status"
INTEGRITY = "desk:integrity"
CHANNEL_STREAM_STATUS = "pub:stream_status"
OUTLIER_REQUESTS = "desk:outlier_requests"  # list of symbols needing second-source confirmation


def quote(symbol: str) -> str:
    return f"desk:quote:{symbol}"


def crosscheck(symbol: str) -> str:
    return f"desk:crosscheck:{symbol}"


def outlier_resolution(symbol: str) -> str:
    return f"desk:outlier:{symbol}:resolution"


def source_state(source: str) -> str:
    return f"desk:source:{source}"


def tick_stream(symbol: str) -> str:
    return f"stream:ticks:{symbol}"


def bar_stream(symbol: str, tf: str) -> str:
    return f"stream:bars:{symbol}:{tf}"
