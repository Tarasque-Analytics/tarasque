# README
### volarbmodel by Leo, Matthew, and Brian

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

## For site developers

Please use Node version 22.21.1 for development purposes

### Below is the default README from React Router

# Welcome to React Router!

A modern, production-ready template for building full-stack React applications using React Router.

[![Open in StackBlitz](https://developer.stackblitz.com/img/open_in_stackblitz.svg)](https://stackblitz.com/github/remix-run/react-router-templates/tree/main/default)

## Features

- 🚀 Server-side rendering
- ⚡️ Hot Module Replacement (HMR)
- 📦 Asset bundling and optimization
- 🔄 Data loading and mutations
- 🔒 TypeScript by default
- 🎉 TailwindCSS for styling
- 📖 [React Router docs](https://reactrouter.com/)

## Getting Started

### Installation

Install the dependencies:

```bash
npm install
```

### Development

Start the development server with HMR:

```bash
npm run dev
```

Your application will be available at `http://localhost:5173`.

## Building for Production

Create a production build:

```bash
npm run build
```

## Deployment

### Docker Deployment

To build and run using Docker:

```bash
docker build -t my-app .

# Run the container
docker run -p 3000:3000 my-app
```

The containerized application can be deployed to any platform that supports Docker, including:

- AWS ECS
- Google Cloud Run
- Azure Container Apps
- Digital Ocean App Platform
- Fly.io
- Railway

### DIY Deployment

If you're familiar with deploying Node applications, the built-in app server is production-ready.

Make sure to deploy the output of `npm run build`

```
├── package.json
├── package-lock.json (or pnpm-lock.yaml, or bun.lockb)
├── build/
│   ├── client/    # Static assets
│   └── server/    # Server-side code
```

## Styling

This template comes with [Tailwind CSS](https://tailwindcss.com/) already configured for a simple default starting experience. You can use whatever CSS framework you prefer.

---

Built with ❤️ using React Router.
