// # centrally, we show the ticker "price arbitrage map" - for this we will need concurrent data from a new run, i also want hover over functionability to show off the specific call price and strike price
// # on the bottom i want to show the top ten predictors by a metric of Prob. of profit and getEnabledCategorie
import { useTickerData } from '~/context/TickerDataContext';
import Placeholder from '../ui/placeholder';
import { useState, useMemo } from 'react';
import {
  Chart as ChartJS,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from 'chart.js';
import { Scatter } from 'react-chartjs-2';

ChartJS.register(LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

export default function Options() {
  const { opportunities, meta } = useTickerData();
  const [selectedExpiry, setSelectedExpiry] = useState<string | null>(null);
  
  const spotPrice = meta?.spot_price;

  // Get unique expiry dates and sort them
  const expiryDates = useMemo(() => {
    if (!opportunities || opportunities.length === 0) return [];
    const unique = [...new Set(opportunities.map(o => o.expiry))].sort();
    return unique;
  }, [opportunities]);

  // Set default expiry on first load
  useMemo(() => {
    if (expiryDates.length > 0 && !selectedExpiry) {
      setSelectedExpiry(expiryDates[0]);
    }
  }, [expiryDates, selectedExpiry]);

  // Filter data for selected expiry
  const filteredData = useMemo(() => {
    if (!opportunities || !selectedExpiry) return [];
    return opportunities.filter(o => o.expiry === selectedExpiry);
  }, [opportunities, selectedExpiry]);

  // Separate calls and puts by market and model prices
  const callMktData = useMemo(() => {
    return filteredData
      .filter(o => o.type === 'call')
      .map(o => ({
        x: o.strike,
        y: o.mkt_px,
        symbol: o.symbol,
        edge_pct: o.edge_pct,
      }));
  }, [filteredData]);

  const callModelData = useMemo(() => {
    return filteredData
      .filter(o => o.type === 'call')
      .map(o => ({
        x: o.strike,
        y: o.model_px,
        symbol: o.symbol,
        edge_pct: o.edge_pct,
      }));
  }, [filteredData]);

  const putMktData = useMemo(() => {
    return filteredData
      .filter(o => o.type === 'put')
      .map(o => ({
        x: o.strike,
        y: o.mkt_px,
        symbol: o.symbol,
        edge_pct: o.edge_pct,
      }));
  }, [filteredData]);

  const putModelData = useMemo(() => {
    return filteredData
      .filter(o => o.type === 'put')
      .map(o => ({
        x: o.strike,
        y: o.model_px,
        symbol: o.symbol,
        edge_pct: o.edge_pct,
      }));
  }, [filteredData]);

  if (!opportunities || opportunities.length === 0) {
    return (
      <div>
        <Placeholder title="Something went wrong" />
      </div>
    );
  }

  // Custom plugin to draw spot price line
  const spotPriceLinePlugin = {
    id: 'spotPriceLine',
    afterDatasetsDraw(chart: any) {
      if (!spotPrice) return;
      
      const xScale = chart.scales.x;
      const yScale = chart.scales.y;
      const spotX = xScale.getPixelForValue(spotPrice);
      
      chart.ctx.save();
      chart.ctx.strokeStyle = 'black';
      chart.ctx.setLineDash([5, 5]);
      chart.ctx.lineWidth = 2;
      chart.ctx.beginPath();
      chart.ctx.moveTo(spotX, yScale.top);
      chart.ctx.lineTo(spotX, yScale.bottom);
      chart.ctx.stroke();
      
      // Draw label
      chart.ctx.font = 'bold 12px Arial';
      chart.ctx.fillStyle = 'black';
      chart.ctx.textAlign = 'center';
      chart.ctx.fillText(`Spot Price: $${spotPrice.toFixed(2)}`, spotX, yScale.top - 10);
      
      chart.ctx.restore();
    },
  };

  const chartData = {
    datasets: [
      {
        label: 'Calls (Market)',
        data: callMktData,
        borderColor: 'rgb(34, 197, 94)',
        backgroundColor: 'rgba(34, 197, 94, 0.7)',
        pointStyle: 'cross',
        pointRadius: 8,
        pointBorderWidth: 2,
        showLine: false,
      },
      {
        label: 'Calls (Model)',
        data: callModelData,
        borderColor: 'rgb(59, 130, 246)',
        backgroundColor: 'rgba(59, 130, 246, 0.7)',
        pointStyle: 'circle',
        pointRadius: 6,
        showLine: false,
      },
      {
        label: 'Puts (Market)',
        data: putMktData,
        borderColor: 'rgb(239, 68, 68)',
        backgroundColor: 'rgba(239, 68, 68, 0.7)',
        pointStyle: 'cross',
        pointRadius: 8,
        pointBorderWidth: 2,
        showLine: false,
      },
      {
        label: 'Puts (Model)',
        data: putModelData,
        borderColor: 'rgb(249, 115, 22)',
        backgroundColor: 'rgba(249, 115, 22, 0.7)',
        pointStyle: 'circle',
        pointRadius: 6,
        showLine: false,
      },
    ],
  };

  const chartOptions = {
    responsive: true,
    plugins: {
      spotPriceLine: {} as any,
      title: {
        display: true,
        text: `Options Chain - Expiry: ${selectedExpiry}`,
      },
      legend: {
        position: 'top' as const,
      },
      tooltip: {
        callbacks: {
          label: function (context: any) {
            const point = context.raw;
            return `Strike: $${point.x}, Contract: $${point.y.toFixed(2)}, Edge: ${point.edge_pct.toFixed(1)}%`;
          },
        },
      },
    },
    scales: {
      x: {
        title: {
          display: true,
          text: 'Strike Price ($)',
        },
        type: 'linear' as const,
      },
      y: {
        title: {
          display: true,
          text: 'Option Price ($)',
        },
      },
    },
  };

  return (
    <div>
      <Placeholder title="Options" />
      
      <div>
        <label>
          Select Expiry Date:
          <select 
            value={selectedExpiry || ''} 
            onChange={(e) => setSelectedExpiry(e.target.value)}
            className="ml-2 p-2"
          >
            {expiryDates.map(date => (
              <option key={date} value={date}>{date}</option>
            ))}
          </select>
        </label>
      </div>

      {selectedExpiry && filteredData.length > 0 && (
        <Scatter data={chartData} options={chartOptions} plugins={[spotPriceLinePlugin]} />
      )}
    </div>
  );
}