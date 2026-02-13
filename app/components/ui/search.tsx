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
      required
    />
  );
}
