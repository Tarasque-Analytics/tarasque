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
import { useEffect, useState } from "react";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

export default function MonteCarlo() {
  const { monteCarloData } = useTickerData();
  const [isDark, setIsDark] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    setIsDark(mq.matches);
    
    const handler = (e: MediaQueryListEvent) => setIsDark(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);

  const textColor = isDark ? "#ffffff" : "#111111";
  const mutedText = isDark ? "#aaaaaa" : "#555555";
  const gridColor = isDark ? "rgba(255, 255, 255, 0.1)" : "rgba(0, 0, 0, 0.1)";

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
        color: textColor,
      },
      legend: {
        position: "top" as const,
        labels: {
          color: textColor,
        },
      },
    },
    scales: {
      x: {
        title: {
          display: true,
          text: "Day",
          color: textColor,
        },
        ticks: {
          color: mutedText,
          autoSkip: false,
          callback: function (value: string | number) {
            return Number(value) % 5 === 0 ? value : ""; // Show every 5th
          },
        },
        grid: {
          color: gridColor,
        },
      },
      y: {
        title: {
          display: true,
          text: "Price ($)",
          color: textColor,
        },
        ticks: {
          color: mutedText,
        },
        grid: {
          color: gridColor,
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
