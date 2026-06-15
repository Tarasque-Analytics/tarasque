import type { LoaderFunctionArgs } from "react-router";
import SectorView from "../pages/Sector";

// Route loader: validates the sector param. Sector data wiring is not implemented yet.
export async function loader({ params }: LoaderFunctionArgs) {
  const { sector } = params;

  if (!sector) {
    throw new Response("Sector parameter is required", { status: 400 });
  }

  return { sector };
}

export default SectorView;
