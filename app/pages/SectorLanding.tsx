import SectorSearch from "~/components/ui/sector_search";

/**
 * /sector landing page.
 *
 * Hosts a centered sector search. The sector search is a placeholder for now (no sector
 * directory/data wired yet) — see ui/sector_search.tsx.
 */
export default function SectorLanding() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="w-full max-w-md">
        <SectorSearch />
      </div>
    </div>
  );
}
