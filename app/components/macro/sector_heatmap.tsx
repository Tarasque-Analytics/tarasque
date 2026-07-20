import { Card, Empty } from "~/components/ui/section";

// Sector heatmap table for /macro (center column, below the regime scatter). Supporting layout card
// — NOT specified by #132–#135; scaffolded as a labeled empty card so the 3-column grid matches the
// mockup. No fabricated data; the table is deferred to the finance-team content pass. See
// app/CLAUDE.md.
export default function SectorHeatmap() {
  return (
    <Card>
      <Header />
      <Empty>Sector heatmap coming soon.</Empty>
    </Card>
  );
}

function Header() {
  return (
    <div>
      <h2 className="text-lg font-semibold tracking-tight text-(--text-primary)">Sector heatmap</h2>
      <p className="mt-0.5 text-sm text-(--text-muted)">By GICS sector</p>
    </div>
  );
}
