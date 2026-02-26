import { useState, useMemo } from "react";
import { Pie } from "react-chartjs-2";
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from "chart.js";
import { usePortfolioData } from "~/context/PortfolioDataContext";
import { getCurrentPrices } from "./portfolio_utils";

ChartJS.register(ArcElement, Tooltip, Legend);

export default function PortfolioPieChart() {
    const holdings = usePortfolioData().holdings;
    const prices = getCurrentPrices(holdings.map(h => h.ticker));
    const chartData = useMemo(() => {
        const totalValue = holdings.reduce(
            (sum, holding) => sum + holding.quantity * prices[holding.ticker],
            0
        );

        return {
            labels: holdings.map(h => h.ticker),
            datasets: [
                {
                    data: holdings.map(
                        holding => (holding.quantity * prices[holding.ticker]) / totalValue * 100
                    ),
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
    }, [holdings, prices]);

    const options = {
        responsive: true,
        plugins: {
            legend: {
                display: false
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