import { useMemo } from "react";
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
import { usePortfolioData } from "~/context/PortfolioDataContext";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend);

export default function PortfolioGraph() {
  const holdings = usePortfolioData().holdings;
  const labels = getLastNDays(30); // Get last 30 days for x-axis labels
  // Let's make a component to change this dynamically via user input

  const chartData = useMemo(() => {
    // Generate random portfolio values for demonstration
    // TODO: Replace with actual historical portfolio value data when available
    const values = labels.map((_, index) => {
      const baseValue = holdings.reduce((sum, h) => sum + h.quantity * h.price_bought, 0);
      const variance = (Math.random() - 0.5) * 200 + baseValue;
      return Math.max(variance, baseValue * 0.8); // Ensure positive values
    });

    return {
      labels,
      datasets: [
        {
          label: "Portfolio Value",
          data: values,
          borderColor: "#36A2EB",
          backgroundColor: "rgba(54, 162, 235, 0.1)",
          borderWidth: 2,
          fill: true,
          tension: 0.4,
          pointRadius: 0,
          // pointBackgroundColor: "#36A2EB",
          // pointBorderColor: "#fff",
          // pointBorderWidth: 2,
        },
      ],
    };
  }, [holdings, labels]);

  const options = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: false,
        // position: "top" as const,
        // labels: {
        //     font: { size: 12 },
        // },
      },
      title: {
        display: false,
      },
    },
    scales: {
      y: {
        beginAtZero: false,
        ticks: {
          font: { size: 10 },
        },
      },
      x: {
        ticks: {
          font: { size: 10 },
        },
      },
    },
  };

  return (
    <div className="portfolio-graph-container">
      <div className="portfolio-graph-wrapper">
        <Line data={chartData} options={options} />
      </div>
    </div>
  );
}

function getLastNDays(n: number): string[] {
  const dates = [];
  const date = new Date();
  for (let dayAgo = n - 1; dayAgo >= 0; dayAgo--) {
    const currentDate = new Date(date);
    currentDate.setDate(currentDate.getDate() - dayAgo);
    dates.push(currentDate.toISOString().split("T")[0]); // Format as YYYY-MM-DD
  }
  return dates;
}
