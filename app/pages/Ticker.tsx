import { Link, useParams } from "react-router";

export default function TickerView() {
  const { symbol } = useParams();
  return (
    <div>
      <h1>Ticker: {symbol}</h1>
      <p>Ticker details here. (Try changing the URL)</p>
      <Link to="/">Go home</Link>
    </div>
  );
}
