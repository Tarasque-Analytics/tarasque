// this section shoule be a grid view with top down lists, one of which being top sectors of the year, another being sectors with the highest VRP (volatility risk premiums), and then the lowest, then a few others based on how many we can fit, id also like hover mechanics on these too
export default function SectorView() {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Sector View</h2>
      <div className="bg-gray-100 rounded w-full aspect-square flex items-center justify-center">
        <svg className="w-24 h-24 text-gray-300" fill="currentColor" viewBox="0 0 24 24">
          <rect width="24" height="24" fill="#f3f4f6" />
          <text x="12" y="12" textAnchor="middle" dy="0.3em" fill="#9ca3af" fontSize="10" fontFamily="sans-serif">
            Placeholder
          </text>
        </svg>
      </div>
    </div>
  );
}