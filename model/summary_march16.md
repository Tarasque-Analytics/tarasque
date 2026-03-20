Web application:
 The volarbear web app provides a daily/prompted update to uncertainty estimates of a stock, allowing users to understand stock-own uncertainty, volatility feature importance via SHAP, uncertainty against the sector, market, etc. Additionally allowing full portfolio analysis, including current delta snapshots, risk snapshots, etc.

The model:
The volarbear model ingests data from alpaca for use by a 10 year backtest suite using several ML methods including but not limited to XGBoost, Random Forest, LassoCV, and classical Garch stabilizers. 

These models are used to forecast realized volatility (RV or modelRV), using the karman-glass definition of volatility (Open, High, Low, Close),   and build feature importance to tell us what is currently driving the stock, and how thats changed over time. 
Forecast is set up as a monotonic cublic spline that fits a quadratic onto the forecasted points giving smoother forecasts than the linear one before it.
All four models are present and make their own estimation, they are then given votes proportional to their inverse-error.

The Backtest:
The backtest is built from stock data from 03-01-2016 to 03-16-2026 tracking model validity, the spread between model volatility and market implied volatility, as well as the regimes and velocities the stocks are moving at. 

Additionals:
Modeling Z score distribution over time would make for an interesting way to conceptualize “regimes”
Included stocks must have >50millionUSD daily volume (good for both options, usability, and model training).
Were going to assign sector IDS to each company, and cap size markers, among others (i.e., apple would be classed as both tech and mega cap). [ can likely pull the GICS or global industry classification standard codes and measuring market cap ]
Conducting residual analysis on the outputs is requisite. Sorting by top 100 most erroneous stocks or days will be crucial to helping us guide the model.
SHAP (SHapley Additive exPlanations) game theory based, tells about feature importance, exactly how much, which direction its heading in - will allow for the app to display a force plot for every stock, allowing us to see where correlations are going.
Going to need to log historical fed dates and earnings dates (ouch)
Going to want to write a script for every day to push market data for all stocks to make db complete again.

Validity
Mincer-zarnowitz regression using the outputs (easy to conceptualize)
.   
Asymmetric QLIKE (quasi-liklihood) loss function- robust loss function used to evaluate vol forecasts designed to penalixe understamation and overstimation differently, 
Event capture - tracking 2 stdev events like cascades, success is defined by how many of those events occurred when the model spikes before the stock does.

Other requisite fixes and such:
- find real interpolated market IV rather than computing locally or alternatively copy standardized logic
- scrap options printout
- reintroduce sector proxies with stiff constraints, pick top two for each stock, regress against one another, use the rolling residual variance of one to isolate its additional/different variance (i.e., amazon would be tech and consumer products)
- engineering features on a sparse group of variables, like rolling variance, vol expansions, drawdown depth, rolling correlations, etc
- addings dividend payment days not just earnings for additional volatility
- limit constraints on mL. theyre already built not to overfit.
- filter out stocks with little liquidity
- passive index analysis, i.e., say vix is low because the sandp isnt moving much but 30% of the companoes are in high percentile risk situations, we call that time to go. 
- find unpredicted wedges in quiet markets, or low wedges in crazy markets, both value
- orthogonalization: regressing two highly correlated variables against one another for unique signals - also can be used to create "betas" for each equity 
- short term momentum & price regime (current price / rolling 252 day high)-1 gives the model an understanding of how far it is from its recent peak

-for strategy backtest, it would be wise for wedge to signal enter and exit from a position
- add to ui wether the stock is coupling or detaching from the sector - shows of idiosyncratic risk
- check out d3.js and highcharts for custom math