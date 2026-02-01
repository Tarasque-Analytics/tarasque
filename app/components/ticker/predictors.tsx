// using the top 10 predictors of volatility, the shart should show percentage weights in order of significance which factors contribute to volatility

export default function Predictors() {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <h2 className="text-lg font-semibold text-gray-900 mb-4">Predictors</h2>
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
