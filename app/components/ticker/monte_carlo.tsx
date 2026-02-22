import { useTickerData } from "~/context/TickerDataContext";
import Placeholder from "../ui/placeholder";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
} from "chart.js";
import { Line } from "react-chartjs-2";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

export default function MonteCarlo() {
  const { monteCarloData } = useTickerData();
  if (!monteCarloData) {
    return (
      <div>
        <Placeholder title="Something went wrong" />
      </div>
    );
  }

  const chartOptions = {
    responsive: true,
    plugins: {
      title: {
        display: true,
        text: "20-Day Monte Carlo",
      },
      legend: {
        position: 'top' as const,
      },
    },
    scales: {
      x: {
        title: {
          display: true,
          text: "Day",
        },
        ticks: {
          autoSkip: false,
          callback: function (value: string | number) {
            return Number(value) % 5 === 0 ? value : ""; // Show every 5th
          },
        },
      },
      y: {
        title: {
          display: true,
          text: "Price ($)",
        },
      },
    },
    drawActiveElementsOnTop: true,
  };

  const data = {
    labels: monteCarloData?.steps || [],
    datasets: [
      {
        label: "p95",
        data: monteCarloData?.p95 || [],
        borderColor: "rgba(0, 255, 0, 0.5)",
        backgroundColor: "rgba(0, 255, 0, 0.5)",
      },
      {
        label: "mean",
        data: monteCarloData?.mean || [],
        borderColor: "rgba(0, 0, 255, 0.5)",
        backgroundColor: "rgba(0, 0, 255, 0.5)",
      },
      {
        label: "p05",
        data: monteCarloData?.p05 || [],
        borderColor: "rgba(255, 0, 0, 0.5)",
        backgroundColor: "rgba(255, 0, 0, 0.5)",
      },
    ],
  };

  return (
    <div>
      <Placeholder title="Monte Carlo Results" />
      <Line options={chartOptions} data={data} />
    </div>
  );
}
