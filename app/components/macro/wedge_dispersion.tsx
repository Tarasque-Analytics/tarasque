import { Card, Empty } from "~/components/ui/section";

// Wedge-dispersion histogram for /macro (right column). Supporting layout card — NOT specified by
// #132–#135; scaffolded as a labeled empty card so the 3-column grid matches the mockup. No
// fabricated data; the histogram itself is deferred to the finance-team content pass (no chart is
// built in this scaffold). See app/CLAUDE.md.
export default function WedgeDispersion() {
  return (
    <Card>
      <Header />
      <Empty>Dispersion histogram coming soon.</Empty>
    </Card>
  );
}

function Header() {
  return (
    <div>
      <h2 className="text-lg font-semibold tracking-tight text-(--text-primary)">
        Wedge dispersion
      </h2>
      <p className="mt-0.5 text-sm text-(--text-muted)">Cross-section VRP histogram</p>
    </div>
  );
}
