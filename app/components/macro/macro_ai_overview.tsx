import { Card, Empty } from "~/components/ui/section";

// Macro AI overview text panel for /macro (right column). Supporting layout card — NOT specified by
// #132–#135; scaffolded as a labeled empty card so the 3-column grid matches the mockup. No
// fabricated data. See app/CLAUDE.md.
export default function MacroAiOverview() {
  return (
    <Card>
      <Header />
      <Empty>AI overview coming soon.</Empty>
    </Card>
  );
}

function Header() {
  return (
    <div>
      <h2 className="text-lg font-semibold tracking-tight text-(--text-primary)">
        Macro AI overview
      </h2>
      <p className="mt-0.5 text-sm text-(--text-muted)">Generated commentary</p>
    </div>
  );
}
