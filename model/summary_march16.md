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

- use select sector etfs (XLK, XL(X), etc, theyre available on optionmetrics IVYDB)
- options only seem to be available as EOD values

Thus, we will have neither the data nor the compute for intraday strategy backtest on options, which is likely fine because we would have less difficulty with wide bid/ask spreads, and our fear/uncertainty value will line up perfectly with that exact instance. 
Furthermore, when we bring around the debt based model, we can run a regression to find how much variation of the uncertainty metric can be attributed to debt based issues, and of course how much comes from non-systematic factor like human or behavioral fear or uncertainty premia.

- we are likely going to want to push back model backtest farther into the past, into around year 2000
- unfixed parameters (sector correlations) will likely make our model superior to others.
- any structured breaks must be accounted for in one way shape or form for backtest. IE, we must explain structured variances/error clusters for implementation. An example of which is incorperating past & future if planned events like major conferences for tech or quasi-structural release events (ex. phone launch dates in early fall for apple)

- methodology to try out based on 2020 study (Forecasting stock market volatility under parameter and model uncertainty): markov regime switching & time varying parameter model. 
- inflation may be useful to metricize even though it feeds into TLT & USO / all of the rest of the variances - we would need a rolling metric like a rolling change of the breakeven inflation rate on 5 year or 10 year baselines (math is nominal treasury bond - treasuty inflation protected security of the same security)
- we would need to log structural breaks to log - like in the mockup the venezuela incident
- in events, say with BAC and the trump comments on capping apy @ 10%, the sector would have moved with BAC, showing a huge risk premium on all of the companies in that sector, it hasnt reached that same metric since, but the premium is now gone, no idea how that would work with strategy. maybe if premium fades and the stock stays the same price, it locks in?
- tlt is the 20+ year treasuries.
- for metrics to feed into the model, we would need 21d corr, 252 correlation, and the decoupling wedge (21d-252d corr) or something smarter. - it would also tell us to unhook the equity from the sector
- econometric rule of thumb is that we need at least 20 samples for each feature to avoid overfitting 
- etf availabbility is the hardest part of this because USO (oil etf) launched in 2006, HYG in 2007, VIXY in 2011, and TLT in 2002, so our lowground is 2011.
- to work around etf related issues we can splice in crude futures for oil, bofa high yeild index spread, and vixy wirh vix
- conditions of yesteryear carry some weight, but were gonna want to dynamically weight them, say early data weight =1, 10 year old at 0.5, and last year @1.
- actually we dont need to use macro proxies on backtest like we do for new imports, we can use:
SPX instead of SPY
CBOE volatility index instead of VIXY
DXY dollar index over UUP
We can use CL=F (continuous oil futures) instead of USO
Use ICE BOFA HYIO instead of HYG (on fred as BAMLH0A0HYM2)
Swap 10/20yr treasury constant maturtuy rate instead of TLT
- we must avoid revised figures and use point-in-time features 
- a 1000 ticker test would take about a week on my hardware, on matts rig we could prob do it in an hour, it can literally store it inside of the cpu

- minser-zarnowitz (MZ) is the classic test for forcast validity, if we were market makers we would us it. Its likely a first round validity to make sure that the model is actually working.
- event capture validity - risk management metric, to see if model reacts well to binary cliffs, see if FOMC, Earnings, Dividends, are working correctly.
- Fear isolation validity however is going to be particularly difficult - we need to study how a stok moves after the premium expands or compresses. We would need to run a forward returns analysis, and compare against spx baseline - using wedge size, percentile, against sector, against market, etc. We are looking for a high Informational Coefficient (IC), to see if our wedge tells us anything about the next month of that stock - whats the win rate.
- Specifically the test would be a quintile spread analysis - can the model correctly rank the market from safest equities to most dangerous. For everyday the model would rank equities and drop them into ETF esque 'buckets', we would then calculate forward return for each bucket on 1mo and 1q timeframes. it should follow the efficiency frontier. The spread is the return of q5-q1.
- the market is highly effieicnt so, any genuine positive IC is valid (even as low as 0.02), that edge would be swallowed up by transaction costs and taxes, no PnL
- Instituional grade would be 0.05-0.08, if it remains consistent we have a money printer.
- to make sure we have a usable model for a firm, we would need to work on vastly huge companies, so that trading can actually occor without moving the stock. 
- crisis alpha: cant just make money on the 9 year average bull market from 2010 to 2019
- sharpe ration: risk adjusted retrun must be tantamount
- hedge from paper came using west texas intermediate crude oil future (WTI)
- the spread between otm calls and puts (in terms of IV) would be useful for trade direction, sell versus buy. If there were a large skew or spread, there is institutional panic, fear, leading to more expensive puts. If it were priced in with a small skew or spread btween the otm calls and puts, whilst still in high wedge conditions, the uncertainty is bilateral.
- Currently a good example of this is the spread/skew on chevron, as of 3/24 @ 1:26pm, chevron has an overall high percentile IV after a monumental bull-run, ergo the market has placed higher IV on ownside put options, and lesser IV on upside call options, signaling downside protection, ergo a greater tail risk than simply uncertainty risk, both of which are likely high, our model would see this to discount upside potential (assumption*), conversely during/after a bull run if that spread/skew were growing smaller, or simply small, it would be general uncertainty. 
- market makes use volatility to fund hedging risk, they are delta neutral liquidity providers, focused on capturing the bid-ask spread, when their contracts are bought, they are essentially short those puts, and thus short the underlying equity.
- in the current chevron situation, the stock hit 210, institutions have made a fortune and buy otm puts as insurance, calls dry up because the funds are hedged correctly with their equity position. - when the amount of short positions and put holdings grows, we see a downward feedback loop, puts become incredibly expensive.
- our basis for the equity backtest would include recognizing that there is a range of downside priced in, guiding how it uses the wedge.
- the IC measurement i wrote about earlier is a single continous predictive signal against a continous taget, i.e., does the wedge predict return. adding directional conditions will help our sharpe ratio - our strategy is now similar to a "Dynamic Defensive Equity Overlay"
- our plan is to strip the options execution to protect from options market related issues like liquidity vacuums and other risks, a sacrifice of yeild for survival and value. 
- to do this were gonna need four classifications: steady market with significant z score = sell. Bilateral uncetainty with a high z score and a flat skew: neutral risk profile = hold. panic conditions of high wedge and high percentile skew = buy the dip. High wedge and low skew = sell for profits.
- this makes any strategy a systematic, rules based engine designed to make equity weights dynamic, avoiding risk, while harvesting from behavioral panic.
- later to increase upside we can tax harvest via proxy substitution: replacing a loss-burdened equity with one of a similar or better profile to circuvent wash sale protocols and tax loss harvest, ike moving from XOM to CVX.
- we can also direct index etfs, to understand the mathematical disconnect between top down risk on the market aggregated SPY and the cumulative risks of each of the underlying equities (the bottom up risk), so following trends between equities within an index and the index gives us precursor to macro level volatility.
- the plan is gonna need to be sequential, starting with purely delta-1 plays to manage risk and prove IC. the second being adding proxy sub and TLH. the third would introduct VRP harvesting only on the highest conviction trades.

- all in all, we want to create the framework to test our model on with everthing we would need for all of these features that we would deploy later
- we need to build a enough interesting & meaninful correlations within the data for the decision tree models to thrive and give exelent SHAP values as a great black box breaking capiabilitiy. 



- quantitative engine with the core objective of isolating the idiosyncratic volatility risk premium (as a metric of fear or uncertainty) using an additional insurance wedge characteristic (IV for +25 OTM calls, and IV for -25 OTM puts) for a directional index.
- to do this we use fred indicies like SPX, VIX, DXY, CL=F, ICEBOFA, Treasury maturities, etc
- we deploy adaptive heteroskedasticity filters, as a pseudo-vif, dynamically expanding and contracting the z-score demonimator of the wedge based on the velocity of volatility forcing the model to demand a higher threshold of proof during structural market crashes (to avoid catching falling knives)
- we adjust the data structure imporance by implementing exponential sample weighting, low weight in the begining, high towards recency, so the model remembers but doesnt try to use it too much.
- using Point-In-Time, WFA, and proper alignment we prevent LAB.
- we evaluate our model with the Mincer Zarnowize to make sure models are working properly / follow real changes.
- quintile spread to see if there is any difference between model asigned risk and model assigned calm in terms of their returns.
- our anticipated strategies is akin to a dynamic defensive equity overlay, we are using the derivatives market as a constant information feed to trade the underlying equities reducing drawdown and risk.