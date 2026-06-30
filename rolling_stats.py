# -*- coding: utf-8 -*-

"""
Created on 30. 06. 2026

Author: Richard Redina
Email: 195715@vut.cz
Affiliation:
         International Clinical Research Center, Brno
         Brno University of Technology, Brno
GitHub: RicRedi

(._.)
 <|>
_/|_

Description:
    Standalone script computing 7-day rolling mean of daily temperature
    for each sensor defined in vineyard_analyst.yaml.
    Output: PNG plot saved to vystupy/grafy/png/
"""

import os
import yaml
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
CONFIG     = os.path.join(BASE_DIR, "vineyard_analyst.yaml")
OUTPUT_DIR = os.path.join(BASE_DIR, "vystupy", "grafy", "png")
os.makedirs(OUTPUT_DIR, exist_ok=True)

WINDOW_DAYS = 7  # rolling window width

# ── Load config ────────────────────────────────────────────────────────────────
with open(CONFIG, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

date_from = pd.to_datetime(config["date_from"])
date_to   = pd.to_datetime(config["date_to"])
sensors   = config["sensor"]
file_path = config["file_path"]

# ── Plot ────────────────────────────────────────────────────────────────────────
sns.set_style("whitegrid")
palette = sns.color_palette("Set2", len(sensors))

fig, ax = plt.subplots(figsize=(13, 5))

for i, sensor in enumerate(sensors):
    df = pd.read_excel(file_path, sheet_name=sensor, decimal=",")
    df["Datum a čas"] = pd.to_datetime(df["Datum a čas"], dayfirst=True)
    df = df[
        (df["Datum a čas"] >= date_from) &
        (df["Datum a čas"] <= date_to)
    ].copy()

    daily_mean = (
        df.set_index("Datum a čas")["Teplota"]
        .resample("D")
        .mean()
    )
    rolling = daily_mean.rolling(window=WINDOW_DAYS, center=True, min_periods=4).mean()

    ax.plot(
        rolling.index, rolling.values,
        label=f"Čidlo {sensor}",
        color=palette[i],
        linewidth=2.0,
    )

ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m."))
ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
plt.xticks(rotation=45)
ax.set_xlabel("Datum", fontsize=11)
ax.set_ylabel("Teplota (°C)", fontsize=11)
ax.set_title(
    f"{WINDOW_DAYS}denní klouzavý průměr teploty — "
    f"{date_from.strftime('%d.%m.%Y')} až {date_to.strftime('%d.%m.%Y')}",
    fontsize=12,
)
ax.legend(loc="best", fontsize=10)
fig.tight_layout()

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
out_path = os.path.join(OUTPUT_DIR, f"rolling_mean_{timestamp}.png")
fig.savefig(out_path, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Uloženo: {out_path}")
