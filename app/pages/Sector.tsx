import { useParams } from "react-router";

export default function SectorView() {
  const { sector } = useParams<{ sector: string }>();

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="w-full max-w-md bg-white dark:bg-neutral-900 border border-gray-200 dark:border-neutral-700 rounded-xl shadow-sm p-6 text-center">
        <h1 className="text-lg font-semibold mb-2">{sector} sector</h1>
        <p className="text-sm text-gray-400">Sector analytics are coming soon.</p>
      </div>
    </div>
  );
}
