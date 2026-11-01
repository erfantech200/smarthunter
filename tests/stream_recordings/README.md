# Stream recordings

Test-only recordings used by the replay tests (SPEC §22 "replay recorded streams → identical signals").
Files whose names start with `synthetic_` are **hand-written in the provider's wire format**, not real
market data. Real recordings captured from the live feed (Phase 1 live run, `make record-stream`) are
added here with a `recorded_` prefix and the capture date.
