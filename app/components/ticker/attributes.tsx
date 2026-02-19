import { useTickerData } from '~/context/TickerDataContext';
import Placeholder from '../ui/placeholder';

const { meta } = useTickerData();

export default function Attributes() {
  return (
    <div>
      <Placeholder title="Attributes" />
    </div>
  );
}