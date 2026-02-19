import { useTickerData } from '~/context/TickerDataContext';
import Placeholder from '../ui/placeholder';

const { explainability } = useTickerData();

export default function MonteCarlo() {
  return (
    <div>
      <Placeholder title="Monte Carlo Simulation" />
    </div>
  );
}