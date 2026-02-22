import { useTickerData } from "~/context/TickerDataContext";
import Placeholder from "../ui/placeholder";
import { Line } from "react-chartjs-2";
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

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

// From routes/ticker.tsx
// charts:
// monte_carlo:
// graph this: three-column data (p95, mean, p05)
// use steps length for x-axis (bottom left)

// From TickerDataContext.tsx
// monteCarloData: data.charts?.monte_carlo,

// "monte_carlo": {
// "p95": [],
// "p05": [],
// "mean": [],
// "steps": []
// }

export default function MonteCarlo() {
  const { monteCarloData } = useTickerData();

  const options = {
    responsive: true,
    plugins: {
      title: {
        display: true,
        text: "20-Day Monte Carlo",
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
          text: "Price",
        },
        ticks: {
          callback: function (value: string | number) {
            return "$" + value;
          },
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
      <Line options={options} data={data} />
    </div>
  );
}
