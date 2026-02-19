// # centrally, we show the ticker "price arbitrage map" - for this we will need concurrent data from a new run, i also want hover over functionability to show off the specific call price and strike price
// # on the bottom i want to show the top ten predictors by a metric of Prob. of profit and getEnabledCategorie
import { useTickerData } from '~/context/TickerDataContext';
import Placeholder from '../ui/placeholder';

const { monteCarloData } = useTickerData();

export default function Options() {
  return (
    <div>
      <Placeholder title="Options" />
    </div>
  );
}