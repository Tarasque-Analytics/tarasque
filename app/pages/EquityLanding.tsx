import Search from "~/components/ui/search";

/**
 * /equity landing page.
 *
 * Hosts the ticker search relocated out of the navbar — a single centered search that
 * navigates to /equity/:symbol. Intentionally minimal for now.
 */
export default function EquityLanding() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="w-full max-w-md">
        <Search />
      </div>
    </div>
  );
}
