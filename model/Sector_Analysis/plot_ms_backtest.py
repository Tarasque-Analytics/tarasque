import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 1. Load Data
# I'm assuming you saved that output to 'VolarBear_Heavy_Backtest_SOLO.csv'
# If you just copy-pasted it, save it as 'ms_data.csv' first!
try:
    df = pd.read_csv('VolarBear_Heavy_Backtest_SOLO.csv')
except:
    # Fallback if filename is different
    df = pd.read_csv('ms_data.csv')

df['Date'] = pd.to_datetime(df['Date'])
df = df.sort_values('Date')

# 2. Setup Plot (Dark Mode)
plt.style.use('dark_background')
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), sharex=True)

# --- PANEL 1: THE SIGNAL (Z-Score) ---
# Color bars: Green for correct prediction, Red for wrong
colors = ['#00FF00' if w == 1 else '#FF3366' for w in df['Win']]
ax1.bar(df['Date'], df['Z_Score'], color=colors, width=2, alpha=0.8)

# Add "Action Zones"
ax1.axhline(1.5, color='cyan', linestyle='--', alpha=0.5)
ax1.axhline(-1.5, color='cyan', linestyle='--', alpha=0.5)
ax1.text(df['Date'].iloc[0], 1.6, "LONG VOL ZONE (>1.5)", color='cyan', fontsize=8)
ax1.text(df['Date'].iloc[0], -1.8, "SHORT VOL ZONE (<-1.5)", color='cyan', fontsize=8)

ax1.set_ylabel("Z-Score (Signal Strength)", color='white', fontweight='bold')
ax1.set_title("VolarBear Signal History: Morgan Stanley (MS)", color='white', fontsize=16, fontweight='bold')
ax1.grid(color='gray', linestyle=':', alpha=0.3)

# --- PANEL 2: THE ACCURACY (Rolling Win Rate) ---
# 3-Month Rolling Average (63 days)
df['Rolling_Win'] = df['Win'].rolling(63).mean()

# Color logic for the line: Cyan if > 50%, Orange if < 50%
ax2.plot(df['Date'], df['Rolling_Win'], color='white', linewidth=0.5, alpha=0.3) # Thin trace
ax2.plot(df['Date'], df['Rolling_Win'], color='#00FFCC', linewidth=2, label='3-Month Rolling Accuracy')

# Benchmark Line
ax2.axhline(0.5, color='red', linestyle='--', linewidth=1, label='Random Chance (50%)')

# Fill area under curve
ax2.fill_between(df['Date'], df['Rolling_Win'], 0.5, where=(df['Rolling_Win'] >= 0.5), color='#00FFCC', alpha=0.1)
ax2.fill_between(df['Date'], df['Rolling_Win'], 0.5, where=(df['Rolling_Win'] < 0.5), color='red', alpha=0.1)

ax2.set_ylabel("Directional Accuracy", color='white', fontweight='bold')
ax2.legend(loc='upper left')
ax2.grid(color='gray', linestyle=':', alpha=0.3)

# Format Dates
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
plt.xticks(rotation=45)

# Save
plt.tight_layout()
plt.savefig("VolarBear_MS_Analysis.png", dpi=300)
print("Chart generated: VolarBear_MS_Analysis.png")
plt.show()
