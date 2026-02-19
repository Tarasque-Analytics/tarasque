import { useTickerData } from '~/context/TickerDataContext';
import Placeholder from '../ui/placeholder';

export default function MonteCarlo() {
  const { monteCarloData } = useTickerData();

  return (
    <div>
      <Placeholder title="Monte Carlo Simulation" />
    </div>
  );
}