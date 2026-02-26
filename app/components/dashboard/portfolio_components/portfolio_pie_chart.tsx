import { useState, useMemo } from "react";
import { Pie } from "react-chartjs-2";
import { Chart as ChartJS, ArcElement, Tooltip, Legend } from "chart.js";
import { usePortfolioData } from "~/context/PortfolioDataContext";
import { getCurrentPrices } from "./portfolio_utils";
import PieChart from "../../ui/pie_chart";

ChartJS.register(ArcElement, Tooltip, Legend);

export default function PortfolioPieChart() {
    const holdings = usePortfolioData().holdings;
    const prices = getCurrentPrices(holdings.map(h => h.ticker));

    const labels = useMemo(() => holdings.map(h => h.ticker), [holdings]);
    const data = useMemo(() => {
        const totalValue = holdings.reduce((sum, holding) => sum + holding.quantity * prices[holding.ticker], 0);
        return holdings.map(holding => (holding.quantity * prices[holding.ticker]) / totalValue * 100);
    }, [holdings, prices]);


    return (
        <PieChart labels={labels} data={data} title="Portfolio Allocation" showLegend={false} />
    );
}