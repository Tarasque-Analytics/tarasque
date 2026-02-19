import { useTickerData } from '~/context/TickerDataContext';
import Placeholder from '../ui/placeholder';

export default function Attributes() {
  const { meta } = useTickerData();

  return (
    <div>
      <Placeholder title="Attributes" />
    </div>
  );
}