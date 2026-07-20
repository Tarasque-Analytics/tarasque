import { Card, Empty } from "~/components/ui/section";

// Watchlist / stats panel for /macro (left column). Supporting layout card — NOT specified by
// #132–#135; scaffolded as a labeled empty card so the 3-column grid matches the mockup. No
// fabricated data (consistent with the dashboard/sector placeholders). See app/CLAUDE.md.
export default function Watchlist() {
  return (
    <Card>
      <Header />
      <Empty>Watchlist coming soon.</Empty>
    </Card>
  );
}

function Header() {
  return (
    <div>
      <h2 className="text-lg font-semibold tracking-tight text-(--text-primary)">Watchlist</h2>
      <p className="mt-0.5 text-sm text-(--text-muted)">Sectors · tickers</p>
    </div>
  );
}
