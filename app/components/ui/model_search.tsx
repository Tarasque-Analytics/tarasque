/**
 * Placeholder for model search
 *
 * Jumps the user to /model/:symbol
 * As of now there currently isn't any data available to pull from to support the aforementioned page (shap components or any other model outputs for specific tickers)
 * TODO: fetch all available tickers that have model outputs and navigate to /model/:symbol
 */
import { useState, useEffect } from "react";
import { useNavigate } from "react-router";

export default function ModelSearch() {
  const [ticker, setTicker] = useState("");
  const navigate = useNavigate();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (ticker.trim()) {
      navigate(`/model/${ticker.toUpperCase()}`);
      setTicker("");
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="text"
        placeholder="Search for SHAP"
        onChange={(e) => setTicker(e.target.value)}
        aria-label="Search for SHAP"
        className="model-search-input"
      />
    </form>
  );
}
