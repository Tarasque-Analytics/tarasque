// uncomment below once SectorDataPayload exists if applicable - probably a different payload than tickers
// import type { SectorDataPayload } from "../context/SectorDataContext";
import type { LoaderFunctionArgs } from "react-router";
import SectorView from "../pages/Sector";

// Route loader: fetch sector data from backend API
export async function loader({ params }: LoaderFunctionArgs)

// uncomment below once SectorDataPayload exists if applicable
// : Promise<SectorDataPayload> 
{
  const { sector } = params;
  
  if (!sector) {
    throw new Response("Sector parameter is required", { status: 400 });
  }
  
  try {

    // ditto, return statement is placeholder for now
    return ("yo");
  } catch (error) {
    throw new Response(
      `Failed to load data for ${sector}: ${error instanceof Error ? error.message : "Unknown error"}`,
      { status: 404 }
    );
  }
}


export default SectorView;
