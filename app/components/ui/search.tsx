// probably simply a ticker search, no need for fuzzys yet, however lowercase/upercase shouldnt be an issue if at all possible
import { useState } from "react";


// THIS IS A PLACEHOLDER FOR WHAT IT WOULD LOOK LIKE
export default function Search() {
  const [ticker, setTicker] = useState("");
  
  return (
    <input
      type="text"
      placeholder="Search for ticker..."
      value={ticker}
      onChange={(e) => setTicker(e.target.value)}
      className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
      required
    />
  );
}
