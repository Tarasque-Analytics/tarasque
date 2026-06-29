import { Card, Empty } from "~/components/ui/section";

// Fed / macro events list for /macro (right column). Supporting layout card — NOT specified by
// #132–#135; scaffolded as a labeled empty card so the 3-column grid matches the mockup. No
// fabricated data. Market-wide events (CPI/FOMC/NFP) come from macro_calendar, not event_history
// (see backend/CLAUDE.md "Event model"). See app/CLAUDE.md.
export default function MacroEvents() {
  return (
    <Card>
      <Header />
      <Empty>Macro events coming soon.</Empty>
    </Card>
  );
}

function Header() {
  return (
    <div>
      <h2 className="text-lg font-semibold tracking-tight text-(--text-primary)">
        Fed / macro events
      </h2>
      <p className="mt-0.5 text-sm text-(--text-muted)">CPI · FOMC · NFP</p>
    </div>
  );
}
