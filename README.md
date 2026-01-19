# README
### volarbmodel by Leo

Volatility Arbitrage (vol arb)

(WIP)  
The volarbmodel_full.py file runs the model for the first 75 (alphabetical) tickers from the S&P 500.  
The volarbmodel_short.py and volarbmodel_short.txt files are identical in content, and contain a ticker-specific version of the flow.  
The summary_writeup.md file contains the Google Doc writeup, reformatted and corrected.  

Benchmark Jan 18, 2026:  
A: 2:42  
AAPL: 6:30  
Config:  
TOTAL_AUM = 20000  
OPTIONS_BUDGET = TOTAL_AUM * 0.10  
WFA_STEP_DAYS = 25  
WFA_NUM_STEPS = 5  
Specs:  
AMD Ryzen 7 7800X3D 8-Core (bottleneck)  
64GB DDR5 4800MHz (underclocked from 6400MHz)  

Model description: this model uses machine learning models (Random Forest & XGBoost) and factor & macroeconomic variables (ex: tech sector etf as an aggregator of factor exposure) to track panel correlation and understand historical (5yr) correlations - building an exposure map / understanding the movements of the stock. With this information, the model then judges which direction (less or more volatile) each of its factors is moving towards to recalculate its estimate for volatility. Using this estimate, and the RMSE (Root Mean Squared Error) and a pseudo-VIF (Variance inflaion factor) the model creates a Z-like statistic to quantify statistical dissimilarity of prediction vs market IV. 

This gap between prediction is not in and of itself profit - it can show both real arbitrage and market fear priced in - especially when market IV > Model RV, in this case hesitate, however from what I have seen thus far if Model RV > Market IV, guns should metaphorically blaze. 

In a former tool which i will post to the github eventually can be used as a research tool if the overnight tracker / autonomous model finds ticker/expiry combos that are statistically significant - which shows our best "deal" and a ton of other useful metrics. 

The next steps I wish to add include reintroducing lasso regression to the ensemble which is really just a dichotomy right now, and to build a dashboard for this model to pipeline into that runs analyses on our* positions.

Our* - this model's best implememtation is in a quasi-quant-hedge-fund currently on a paper trader but soon we will run it on real hard earned cash.

There are two runnable models in the GitHub Currently (1/19), the fist of which is the overnight model that runs on a chunk of the S&P500, the second of which is an analysis tool if you want to check out more information on a single ticker and date combo. 
