import { apiGet } from "@/lib/api";

export const dynamic = "force-dynamic";

type Heartbeat = { service?: string; status: string; detail?: string; at?: string };
type ConfigStatus = {
  env: string;
  assets: string[];
  market_data_provider: string;
  open_questions: string[];
  provider_keys_configured: Record<string, boolean>;
};

const STATUS_COLOUR: Record<string, string> = {
  ok: "text-emerald-400",
  idle: "text-sky-400",
  halted: "text-amber-400",
  degraded: "text-amber-400",
  missing: "text-red-400",
};

export default async function Overview() {
  const [services, config] = await Promise.all([
    apiGet<Record<string, Heartbeat>>("/health/services"),
    apiGet<ConfigStatus>("/health/config"),
  ]);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-xl font-semibold">Trade Desk</h1>
        <p className="text-sm text-neutral-400">
          Phase 0 scaffold. No market data is connected yet, so there is nothing to analyse. This page shows system
          health only.
        </p>
      </header>

      <section>
        <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-neutral-400">Services</h2>
        {services.ok ? (
          <ul className="divide-y divide-neutral-800 rounded border border-neutral-800">
            {Object.entries(services.data).map(([name, hb]) => (
              <li key={name} className="flex items-baseline justify-between gap-4 p-2 text-sm">
                <span className="font-mono">{name}</span>
                <span className="flex-1 truncate text-neutral-500">{hb.detail}</span>
                <span className={STATUS_COLOUR[hb.status] ?? "text-neutral-300"}>{hb.status}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-red-400">API unreachable: {services.error}</p>
        )}
      </section>

      {config.ok && (
        <section className="grid gap-4 sm:grid-cols-2">
          <div>
            <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-neutral-400">Universe</h2>
            <div className="flex flex-wrap gap-2">
              {config.data.assets.map((a) => (
                <span key={a} className="rounded border border-neutral-800 px-2 py-1 font-mono text-sm">
                  {a}
                </span>
              ))}
            </div>
            <p className="mt-2 text-xs text-neutral-500">Price feed: {config.data.market_data_provider}</p>
          </div>
          <div>
            <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-neutral-400">Open decisions</h2>
            {config.data.open_questions.length === 0 ? (
              <p className="text-sm text-emerald-400">None</p>
            ) : (
              <ul className="list-inside list-disc text-sm text-amber-300">
                {config.data.open_questions.map((q) => (
                  <li key={q} className="font-mono">
                    {q}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
