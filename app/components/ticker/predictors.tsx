// using the top 10 predictors of volatility, the shart should show percentage weights in order of significance which factors contribute to volatility
import { useTickerData } from '~/context/TickerDataContext';
import Placeholder from '../ui/placeholder';

export default function Predictors() {
  const { explainability } = useTickerData();

  return (
    <div>
      <Placeholder title="Predictors" />
    </div>
  );
}
