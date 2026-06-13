// Page-level fallback for /equity/:symbol when the DB-backed equity payload is unavailable
// (the route loader returns null on fetch failure). Presentational only — no router/loader/context
// dependencies, so it renders from a single optional `symbol` prop and is unit-testable in isolation.

interface EquityUnavailableProps {
  symbol?: string;
}

export default function EquityUnavailable({ symbol }: EquityUnavailableProps) {
  return (
    <div
      role="alert"
      className="panel flex flex-col items-center justify-center gap-2 p-10 text-center"
    >
      <h2 className="text-xl font-semibold text-(--text-primary)">Equity data unavailable</h2>
      <p className="max-w-md text-sm text-(--text-secondary)">
        {symbol
          ? `We couldn't load data for ${symbol.toUpperCase()} right now. The data service may be down, or this symbol may not be available.`
          : "We couldn't load equity data right now. The data service may be down, or this symbol may not be available."}
      </p>
      <p className="text-xs text-(--text-muted)">Please try again in a moment.</p>
    </div>
  );
}
