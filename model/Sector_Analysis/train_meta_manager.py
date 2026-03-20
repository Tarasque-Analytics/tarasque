import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import joblib

# 1. INGEST THE "SECTOR SWEEP" DATA
file_path = "VolarBear_Heavy_Backtest_SECTOR_SWEEP.csv"

try:
    df = pd.read_csv(file_path)
    print(f"[LOADED] {len(df)} trade signals from Sector Sweep.")
except FileNotFoundError:
    print("Error: File not found.")
    exit()

# 2. FEATURE ENGINEERING (The "Manager's" Inputs)
# We adapt this to work WITHOUT the RMSE column.

# Feature A: Conviction Magnitude
df['Z_Abs'] = df['Z_Score'].abs()

# Feature B: Volatility Regime (Forecast)
# Does the model win more when Vol is High (0.40) or Low (0.15)?
# We normalize it so the model understands "High" relative to the dataset
df['Vol_Level'] = df['Forecast']

# Feature C: The Sector (One-Hot Encoding)
# This is crucial. It lets the Manager learn: "Trust MSFT signals, Ignore KO signals"
df_encoded = pd.get_dummies(df, columns=['Ticker'], drop_first=True)

# Define Inputs (X) and Target (Y)
# We use Z-Score, Magnitude, and Volatility Level + Ticker IDs
features = ['Z_Score', 'Z_Abs', 'Vol_Level'] + [c for c in df_encoded.columns if 'Ticker_' in c]

X = df_encoded[features]
y = df_encoded['Win'] # 1 = Profit, 0 = Loss

print(f"[TRAINING] Training Meta-Manager on {len(features)} features...")

# 3. TRAIN THE MANAGER (Logistic Regression)
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, shuffle=False)

# Balanced class weight ensures it cares equally about Wins and Losses
meta_model = LogisticRegression(max_iter=1000, class_weight='balanced')
meta_model.fit(X_train, y_train)

# 4. THE "TRADE SCORE"
# Generate probabilities (The "Confidence Score" from 0 to 100%)
probs = meta_model.predict_proba(X_test)[:, 1] 

# 5. THE PROFITABILITY CURVE (The "Money Chart")
test_results = X_test.copy()
test_results['Win'] = y_test
test_results['Trade_Score'] = probs

# Group by Trade Score bins (0.50, 0.60, 0.70, etc.)
# We visualize: "If the Model says 70% confidence, do we actually win 70% of the time?"
test_results['Score_Bin'] = pd.cut(test_results['Trade_Score'], bins=np.arange(0, 1.1, 0.1))
win_rate_by_score = test_results.groupby('Score_Bin', observed=False)['Win'].mean()

print("\n=== THE VOLARBEAR TRADE SCORE RESULTS ===")
print(win_rate_by_score)

# 6. VISUALIZE
plt.style.use('dark_background')
plt.figure(figsize=(12, 6))

# Plot the Bar Chart
sns.barplot(x=win_rate_by_score.index, y=win_rate_by_score.values, palette="viridis")

# Reference Lines
plt.axhline(0.5, color='red', ls='--', label="Random Chance (50%)")
plt.axhline(0.60, color='yellow', ls=':', label="Soft Threshold (60%)")
plt.axhline(0.70, color='cyan', ls='--', label="Actionable Threshold (70%)")

plt.title("Meta-Model Calibration: Win Rate by Trade Score", color='white', fontsize=14)
plt.ylabel("Actual Win Rate", color='white')
plt.xlabel("VolarBear Trade Score (Model Confidence)", color='white')
plt.legend()
plt.tight_layout()

# Save Chart
chart_name = "VolarBear_Trade_Score_Curve.png"
plt.savefig(chart_name)
print(f"\n[SUCCESS] Saved chart to '{chart_name}'")

# 7. SAVE THE BRAIN
# This saves the model so your web app can use it later
joblib.dump(meta_model, "VolarBear_Meta_Manager.pkl")
print("[SAVED] Meta-Model saved as 'VolarBear_Meta_Manager.pkl'")