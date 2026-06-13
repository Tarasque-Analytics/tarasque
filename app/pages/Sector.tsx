import { useParams } from "react-router";
import { useState, useEffect } from "react";

export default function SectorView() {
  const { sector } = useParams<{ sector: string }>();

// Uncomment when sectorDataPayload exists
//   const payloadData = useLoaderData() as SectorDataPayload;
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Data is preloaded from route loader - need only when pulling from DB, maybe
    setIsLoading(false);
  }, []);

  return (
      <div>
        <div className="flex justify-center">Data and Analytics for {sector}</div>
        {/* Component Grid */}
        {isLoading ? (
          <div className="loading-placeholder" />
        ) : (
          <div className="flex flex-col items-center justify-center w-64 h-64 bg-white border border-gray-200 rounded-xl shadow-sm p-4">
            <iframe
              src="https://giphy.com/embed/Q3J5xe18ZEOVZqWA8x" title="tylko jedno w głowie mam"
            />
            <p className="text-xs text-gray-400 mt-2">
              <a>Totally real {sector} sector view page</a>
            </p>
          </div>
        )}
      </div>

  );
}
