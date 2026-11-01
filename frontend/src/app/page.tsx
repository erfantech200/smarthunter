import { apiGet } from "@/lib/api";

export const dynamic = "force-dynamic";

type Heartbeat = { service?: string; status: string; detail?: string; at?: string };
type Issue = { check: string; severity: string; instrument: string | null; source: string | null; message: string };
type MarketStatus = {
  integrity: { status: string; as_of: string; issues: Issue[]; stale_sources: string[] };
  stream: { status: string; connected: boolean; last_message_age_seconds: number | null; per_instrument: Record<string, string> } | null;
  sources: Record<string, string>;
};
type QuoteRow = { bid: string; ask: string; mid: string; spread: string; age_seconds: number; time: string } | null;
type ConfigStatus = { assets: string[]; market_data_provider: string; open_questions: string[] };

const COLOUR: Record<string, string> = {
  ok: "text-emerald-400",
  OK: "text-emerald-400",
  idle: "text-sky-400",
  halted: "text-amber-400",
  degraded: "text-amber-400",
  DEGRADED: "text-amber-400",
  CRITICAL: "text-red-400",
  missing: "text-red-400",
};

function H2({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-neutral-400">{children}</h2>;
}

export default async function Overview() {
  const [services, market, quotes, config] = await Promise.all([
    apiGet<Record<string, Heartbeat>>("/health/services"),
    apiGet<MarketStatus>("/market/status"),
    apiGet<Record<string, QuoteRow>>("/market/quotes"),
    apiGet<ConfigStatus>("/health/config"),
  ]);

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between">
        <h1 className="text-xl font-semibold">Trade Desk</h1>
        {market.ok && (
          <span className={`font-mono text-sm ${COLOUR[market.data.integrity.status] ?? ""}`}>
            data {market.data.integrity.status}
          </span>
        )}
      </header>

      <section>
        <H2>Market data</H2>
        {!market.ok || !quotes.ok ? (
          <p className="text-sm text-red-400">API unreachable</p>
        ) : (
          <>
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-neutral-500">
                <tr>
                  <th className="py-1">Asset</th>
                  <th>Mid</th>
                  <th>Spread</th>
                  <th>Age</th>
                  <th className="text-right">Stream</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800 font-mono">
                {Object.entries(quotes.data).map(([sym, q]) => {
                  const st = market.data.stream?.per_instrument[sym] ?? "missing";
                  return (
                    <tr key={sym}>
                      <td className="py-1">{sym}</td>
                      <td>{q ? q.mid : "—"}</td>
                      <td>{q ? q.spread : "—"}</td>
                      <td>{q ? `${q.age_seconds}s` : "no data"}</td>
                      <td className={`text-right ${COLOUR[st] ?? ""}`}>{st}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-neutral-500">
              Feed {market.data.sources.oanda ?? "unknown"} · cross-check {market.data.sources.twelvedata ?? "unknown"}.
              Missing data is shown as missing, never estimated.
            </p>
            {market.data.integrity.issues.length > 0 && (
              <ul className="mt-2 space-y-1 text-xs">
                {market.data.integrity.issues.slice(0, 12).map((i, n) => (
                  <li key={n} className={COLOUR[i.severity] ?? ""}>
                    [{i.check}] {i.instrument ? `${i.instrument}: ` : ""}
                    {i.message}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </section>

      <section>
        <H2>Services</H2>
        {services.ok ? (
          <ul className="divide-y divide-neutral-800 rounded border border-neutral-800">
            {Object.entries(services.data).map(([name, hb]) => (
              <li key={name} className="flex items-baseline justify-between gap-4 p-2 text-sm">
                <span className="font-mono">{name}</span>
                <span className="flex-1 truncate text-neutral-500">{hb.detail}</span>
                <span className={COLOUR[hb.status] ?? "text-neutral-300"}>{hb.status}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-red-400">API unreachable: {services.error}</p>
        )}
      </section>

      {config.ok && config.data.open_questions.length > 0 && (
        <section>
          <H2>Open decisions</H2>
          <ul className="list-inside list-disc text-sm text-amber-300">
            {config.data.open_questions.map((q) => (
              <li key={q} className="font-mono">
                {q}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
