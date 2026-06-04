/**
 * Sector search — placeholder.
 *
 * The /sector landing page hosts this in place of the (functional) ticker Search. There is no
 * sector directory/index data wired yet, so this is a non-functional placeholder styled to match
 * the ticker search. Wire it up once a sector list + navigation target exists.
 *
 * TODO: fetch the available sectors and navigate to /sector/:sector on select (mirror ui/search.tsx).
 */
export default function SectorSearch() {
  return (
    <input
      type="text"
      placeholder="Search for a sector… (coming soon)"
      disabled
      aria-label="Sector search (coming soon)"
      className="w-full rounded-lg border border-(--panel-border) bg-(--ui-background) px-4 py-2.5 text-sm text-(--text-primary) placeholder:text-(--text-muted) shadow-sm outline-none disabled:cursor-not-allowed disabled:opacity-60"
    />
  );
}
