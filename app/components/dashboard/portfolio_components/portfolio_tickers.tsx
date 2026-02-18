import { useEffect, useState } from "react";
import { Link } from "react-router";
import portfoliodata from "./test_portfolio.json";
import Holding from "./holding";
export default function PortfolioTickers() {

    // Load test data
    const holdings = portfoliodata.holdings;
    for (const holding of holdings) {
        console.log(holding);
    }

    return (
        <div>
            {holdings.map((holding, index) => (
                <Holding key={index} {...holding} />
            ))}
        </div>
    )
}