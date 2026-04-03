Here is the outline for steps involving the volarbear model / tarasque engine:

- Core goals
Overarching objective is to build and deploy a quantitative engine and web application that isolates volatility risk premium (Interpolated Market IV - Model RV) to function as a metric for market implied fear or uncertainty. The strategy is creating a dynamic defensive equity overlay by using derivatives market as an information feed (specifically the wedge) to dictate dynamic equity weights, drawdown risk, and harvest behavioral panics. This is done via an ensemble of tree based / regularized models - stabilized by a classical garch forecast, set to predict garman-klass volatility (Open,High,Low,Close) using inverse-error voting to aggregate and include model outputs based on their strength. The benchmark we have set is achieving an IC between 0.03 & 0.08, demonstrating a robust sharpe ratio solely on equities, and then introducing proxy substitution Tax loss havesting, and Volatility risk premium harvesting overlays. 

- Data Engineering & Feature Adds
-replace mkt IV with a computation for a reliable interpolated measure. 
-test on indexes and splice in newer ones for intraday alpaca.
-map secids, mostly-stiff sector prozies (t2) isolate residual variance between them.
-features: rolling variance, volatility expansions, drawdown depth, rolling correlations (21d vs 252d decoupling wedge), short-term momentum/price regimes, dividend payment dates, and rolling changes between inflation rates (point-in-time).
-create a system to log and account for structural market breaks (geopolitical comments), and planned major corporate events.

- Architecture Modifications
-constrain illiquid companies, require current 100M daily volume in USD.
-model z score dist over time to define distinct market regimes, implement markov regime switching and time varying parameter models.
-regress highly correlated variables (sector etfs) to extract signals and establish dynamic betas for equities.
-implement exponential sample weighting so model prioritizzes recent signals and understanding without forgetting historical baselines.

- Backtest & Validation
-residual analysis: automate isolation and review of the most erroneous specific days and stocks overall.
-MZ reg, qlike (penilize underestimation MORE than overestimation)
-3sigma events
-quintile spread via daily rankings and 21d,63d, and 128d periods.
-strategy sharpe ratio (risk adjusted return)

- UI
-shap plots
-decoupling visuals
-database update automation @4:01

- Concerns
-Survivorship bias of since-2000 testing.
-IC maintaince out-of-sample
-Point in time data (no revised data)
-liquidity traps (we must use robust huge firms)
-we must use exponentially weighted history because some of it is obsolete.

- ideas
-point-in-time (PiT) dynamic universe: a tradable universe that updates daily, monthly, yearly, whenever. A stock enters when it crosses the volume threshold for proper options related data.

- New Model testing versus Feature Engineering
adding new model architectures may help but there is a hierarchy of actions
-1: data quality (PiT, LookAhead Biases, etc)
-2: feature engineering
-3: model specs (regularization limits, depth, error weights)
-4: algorithm choice

- differences between options trading strat and equities
transfers us from of course option execution strat to equity based overlay, using the data from options contracts as an information feild, limiting most fatal execution risks.
Makes the tarasque strategy a systematic equity overlay:
-bypassing liquidity trap and price parody 
-our compute can simply be End-Of-Day (EOD) allowing dynamic effects to be isolated day-by-day.
-delta problem occors: we can still lose even if were right

- Database data and other related notes
From CRSP (Center for research in security prices)
-daily stock file (crsp.dsf)
-PRC (close), OPENPRC(open), ASKHI (high), BIDLO (low)
-VOL (volume), SHROUT (shares outstanding)
-RET (return +dividends), RETX (w/o div)
-DLRET (delisting returns)
-PERMNO (permanant company no#)

OptionMetrics (IVY DB US)
-optionm.voln (standardized imp vol @ fixed dates & deltas)
-optionm.zerocd (risk free rate used by the market)
-optionm.secprd (standardized ticker data)

Compustat (funadmantals and PiTs)
-comp.idxcst_his (when earnings & div announced for gravity)
-comp.funda (sector and industry codes for prozies)

FRED 
-fred.observaions (SPX, VIX, DXY, ICEBOFA)

None of these use the same primary key so were gonna need to use wrds linking tables to like permno to gvkey, and secid to permno.

- Web app & DB vs API notes
-api calls on live pricing, news, and concurrent mkt interpolated vol.
(everything else can be from db)

for web app displays: 
-cross sectional aggregations for sector percentiles, and others
-dist matrix for the pdf to display on bottom left
-interpolated term structure to spline anchor points between iv points on center bottom graph
-script that maps future days to accurately place on future chart
-will need upkeep for past macro event plotting
-subgraph was a simple moving average, we will need either the raw daily wedge + st dev bands or alternatively an exponentially weighted moving average (ewma)

- Mincer-Zarnowitz (MZ) regression
A test on whether the volatility forecasts are unbiased and market-efficient. IE., does the model systematically undershoot or overshoot the real, realized volatility.

Its actually a very simple ordinary least squares regression, RV = alpha + beta*E(RV)+e(i)

for validity, alpha must not be statistically dissimilar from 0, and beta must not be statistically disimilar from 1 - also r^2 will hover below 0.30 and above 0.15 so dont worry.

- Asymmetric QLIKE Loss Function
Logic: standard, or basic spec ML models equally punish absolute errors equally, ergo +5 and -5 are weighted the same way, volatility however is predicted differently, in this context underassesing risk is catastrophic, while overestimating risk is opportunity cost. Our Spec of QLIKE Loss will punish underestimation greater.

- event capture rate metric
Strategy will inevitably be defensive equity, we must then test if the model can recognize conditions for entry and/or exit

To do this we need to define the event (i.e., when RV spikes +2stdevs above rolling mean (quarterly?)) figure out if risk was sitting where it belonged - high percentile, if it was there it captured future risk, if not, shucks.

Success is not "do we predict everything" because thats not how anything works, as long as we can capture some, say one third, its successful in my book.

- Information Coeficient and quartile spread testing
A test of the predictive power of the wedge scores - do they actually help predict risk.

How to:
-Spearman Rank Correlation (IX): rank universe from riskiest to least risky via z score, then rank by 21 day return, regress to find any correlative power.

-Quintile spread: bucket the universe into 5 risk related categories, track average returns of each bucket.

Success:
IC btwn 0.03-0.06
Spread: riskiest must underperform least-risky over time.

- Volarbear Plans -> Tarasque RAAD (Risk and Analytics Dashboard) Execution
 