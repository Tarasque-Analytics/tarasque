# README
### volarbmodel by Leo, Matthew, David, and Calvin

Volatility Arbitrage (vol arb)

(WIP)  
The volarbmodel_full.py file runs the model for the first 75 (alphabetical) tickers from the S&P 500.  
The volarbmodel_short.py and volarbmodel_short.txt files are identical in content, and contain a ticker-specific version of the flow.  
The summary_writeup.md file contains the Google Doc writeup, reformatted and corrected.  

Model description: this model uses machine learning models (Random Forest & XGBoost) and factor & macroeconomic variables (ex: tech sector etf as an aggregator of factor exposure) to track panel correlation and understand historical (5yr) correlations - building an exposure map / understanding the movements of the stock. With this information, the model then judges which direction (less or more volatile) each of its factors is moving towards to recalculate its estimate for volatility. Using this estimate, and the RMSE (Root Mean Squared Error) and a pseudo-VIF (Variance inflaion factor) the model creates a Z-like statistic to quantify statistical dissimilarity of prediction vs market IV. 

This gap between prediction is not in and of itself profit - it can show both real arbitrage and market fear priced in - especially when market IV > Model RV, in this case hesitate, however from what I have seen thus far if Model RV > Market IV, guns should metaphorically blaze. 

In a former tool which i will post to the github eventually can be used as a research tool if the overnight tracker / autonomous model finds ticker/expiry combos that are statistically significant - which shows our best "deal" and a ton of other useful metrics. 

The next steps I wish to add include reintroducing lasso regression to the ensemble which is really just a dichotomy right now, and to build a dashboard for this model to pipeline into that runs analyses on our* positions.

Our* - this model's best implememtation is in a quasi-quant-hedge-fund currently on a paper trader but soon we will run it on real hard earned cash.

There are two runnable models in the GitHub Currently (1/19), the fist of which is the overnight model that runs on a chunk of the S&P500, the second of which is an analysis tool if you want to check out more information on a single ticker and date combo. 


### Below is the default README from React

This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
