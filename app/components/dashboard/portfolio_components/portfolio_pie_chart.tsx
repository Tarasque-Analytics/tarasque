import { useState, useMemo } from "react";
import { Pie } from "react-chartjs-2";
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from "chart.js";
import { usePortfolioData } from "~/context/PortfolioDataContext";
import { getCurrentPrices } from "./portfolio_utils";
import type { ChartOptions } from "chart.js";

ChartJS.register(ArcElement, Tooltip, Legend);

export default function PortfolioPieChart() {
  const holdings = usePortfolioData().holdings;
  const prices = getCurrentPrices(holdings.map((h) => h.ticker));

  const labels = useMemo(() => holdings.map((h) => h.ticker), [holdings]);
  const data = useMemo(() => {
    const totalValue = holdings.reduce(
      (sum, holding) => sum + holding.quantity * prices[holding.ticker],
      0,
    );
    return holdings.map(
      (holding) => ((holding.quantity * prices[holding.ticker]) / totalValue) * 100,
    );
  }, [holdings, prices]);

  const chartData = {
    labels,
    datasets: [
      {
        data,
        backgroundColor: ["#FF6384", "#36A2EB", "#FFCE56", "#4BC0C0", "#9966FF", "#FF9F40"],
        borderColor: "#ffffff",
        borderWidth: 2,
      },
    ],
  };

  const options: ChartOptions<"pie"> = {
    plugins: {
      legend: {
        display: false,
        position: "bottom",
      },
      title: {
        display: true,
        text: "Portfolio Allocation",
      },
    },
  };

  return (
    <div className="flex justify-center items-center">
      <div className="w-full aspect-square">
        <Pie data={chartData} options={options} />
      </div>
    </div>
  );
}
