// runs the lasso hedge model, shows off a sparce hedge that has home hover over features
import { Pie } from "react-chartjs-2";
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from "chart.js";
import type { ChartOptions } from "chart.js";

ChartJS.register(ArcElement, Tooltip, Legend);

interface PieChartProps {
  labels: string[];
  data: number[];
  title?: string;
  showLegend?: boolean;
}

export default function PieChart({
  labels,
  data,
  title = "",
  showLegend = true,
}: PieChartProps) {
  const chartData = {
    labels,
    datasets: [
      {
        data,
        backgroundColor: [
          "#FF6384",
          "#36A2EB",
          "#FFCE56",
          "#4BC0C0",
          "#9966FF",
          "#FF9F40",
        ],
        borderColor: "#ffffff",
        borderWidth: 2,
      },
    ],
  };

  const options: ChartOptions<"pie"> = {
    plugins: {
      legend: {
        display: showLegend,
        position: "bottom",
      },
      title: {
        display: title !== "",
        text: title,
      },
    },
  };

  return (
    <div className="pie-chart-container">
      <div className="pie-chart-wrapper">
        <Pie data={chartData} options={options} />
      </div>
    </div>
  );
}