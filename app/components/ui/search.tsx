import { useState, useEffect } from "react";
import { useNavigate } from "react-router";
import { getAvailableTickers } from "~/utils/tickers";

export default function Search() {
  const [ticker, setTicker] = useState("");
  const [availableTickers, setAvailableTickers] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const navigate = useNavigate();

  // Fetch available tickers on component mount
  useEffect(() => {
    getAvailableTickers()
      .then(setAvailableTickers)
      .finally(() => setIsLoading(false));
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (ticker.trim()) {
      navigate(`/equity/${ticker.toUpperCase()}`);
      setTicker("");
    }
  };

  // Filter tickers based on input (case-insensitive)
  const filteredTickers = availableTickers.filter((t) =>
    t.toUpperCase().includes(ticker.toUpperCase())
  );

  return (
    <form onSubmit={handleSubmit} className="relative w-full">
      <input
        type="text"
        placeholder={isLoading ? "Loading tickers…" : "Search for a ticker…"}
        value={ticker}
        onChange={(e) => setTicker(e.target.value)}
        list="ticker-suggestions"
        disabled={isLoading}
        className="w-full rounded-lg border border-(--panel-border) bg-(--ui-background) px-4 py-2.5 text-sm text-(--text-primary) placeholder:text-(--text-muted) shadow-sm outline-none focus:border-(--text-muted) disabled:opacity-60"
      />
      <datalist id="ticker-suggestions">
        {filteredTickers.map((t) => (
          <option key={t} value={t} />
        ))}
      </datalist>
    </form>
  );
}
