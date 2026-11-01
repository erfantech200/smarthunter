// Server-side helper for talking to the FastAPI backend. Never fabricates data: on failure it
// returns an explicit error the UI shows as a gap (SPEC §3.7).
const API_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

export type Result<T> = { ok: true; data: T } | { ok: false; error: string };

export async function apiGet<T>(path: string): Promise<Result<T>> {
  try {
    const res = await fetch(`${API_URL}${path}`, { cache: "no-store", signal: AbortSignal.timeout(3000) });
    // /health/* returns 503 with a JSON body when something is missing; still show the body.
    const data = (await res.json()) as T;
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
