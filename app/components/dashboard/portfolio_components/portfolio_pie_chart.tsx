import { useState, useMemo } from "react";
import { Pie } from "react-chartjs-2";
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from "chart.js";
import { usePortfolioData } from "~/context/PortfolioDataContext";

ChartJS.register(ArcElement, Tooltip, Legend);

export default function PortfolioPieChart() {
    const holdings = usePortfolioData().holdings;

    const chartData = useMemo(() => {
        const totalValue = holdings.reduce(
            (sum, holding) => sum + holding.quantity * holding.price_bought,
            0
        );

        return {
            labels: holdings.map(h => h.ticker),
            datasets: [
                {
                    data: holdings.map(
                        holding => (holding.quantity * holding.price_bought) / totalValue * 100
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
    }, [holdings]);

    const options = {
        responsive: true,
        plugins: {
            legend: {
                position: "bottom" as const,
            },
        },
    };

    return (
        <div style={{ width: "300px", height: "300px" }}>
            <Pie data={chartData} options={options} />
        </div>
    );
}