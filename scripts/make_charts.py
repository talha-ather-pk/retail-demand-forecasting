"""
Corvane Drugstores: README / site charts.

Input : data_clean/*.csv (run clean.py, forecast.py and drivers.py first)
Output: images/chart_*.png and a smaller copy in site/img/
Run   : python scripts/make_charts.py   (from the project root)
"""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, PercentFormatter
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
C = ROOT / "data_clean"
IMG, SITE = ROOT / "images", ROOT / "site" / "img"
IMG.mkdir(exist_ok=True)
SITE.mkdir(parents=True, exist_ok=True)
NAVY, PRIMARY, COMPARE, GOLD, GOOD, WARN, BAD, SLATE = ("#0B1F3A", "#1F4E79", "#B8C2CF", "#C8A24A", "#0E7C86",
                                                        "#D08C2E", "#B5523B", "#64748B")
plt.rcParams.update({"font.family": "Segoe UI", "font.size": 10, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlesize": 12,
                     "axes.titlelocation": "left", "axes.edgecolor": "#CBD5E1"})
money = FuncFormatter(lambda v, _: f"${v / 1e6:.1f}M" if abs(v) >= 1e6 else f"${v / 1e3:.0f}K")
LABEL = {"naive": "Baseline\n(same day last year)", "prophet": "Prophet", "gbm": "Gradient\nboosting",
         "ensemble": "Ensemble"}


def save(fig, name):
    fig.tight_layout()
    fig.savefig(IMG / name, dpi=150)
    fig.savefig(SITE / name, dpi=110)
    plt.close(fig)
    print(f"wrote images/{name}")


acc = pd.read_csv(C / "accuracy_by_model.csv")
bt = pd.read_csv(C / "backtest_predictions.csv", parse_dates=["date"])
fc = pd.read_csv(C / "forecast_2026.csv", parse_dates=["date"])
daily = pd.read_csv(C / "daily.csv", parse_dates=["date"])
drv = pd.read_csv(C / "driver_effects.csv")
comp = pd.read_csv(C / "competitor_effects.csv")
best = fc["model"].iloc[0]

# 1. accuracy by model ------------------------------------------------------
a = acc[acc.fold == "all"].set_index("model").loc[["naive", "prophet", "gbm", "ensemble"]]
fig, ax = plt.subplots(figsize=(8, 3.8))
cols = [COMPARE if m == "naive" else (PRIMARY if m == best else "#7FA3C7") for m in a.index]
ax.bar([LABEL[m] for m in a.index], a["WAPE"], color=cols)
for i, v in enumerate(a["WAPE"]):
    ax.text(i, v + 0.002, f"{v:.1%}", ha="center", fontweight="bold" if a.index[i] == best else "normal")
ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
cut = 1 - a.loc[best, "WAPE"] / a.loc["naive", "WAPE"]
ax.set_title(f"Forecast error (WAPE) over three 6-week backtests: {cut:.0%} lower than the baseline")
save(fig, "chart_accuracy.png")

# 2. backtest example: chain daily, last fold ------------------------------------
f3 = bt[bt.fold == bt.fold.max()].groupby("date")[["sales", "naive", best]].sum()
f3 = f3[f3["sales"] > 0]
fig, ax = plt.subplots(figsize=(10, 3.8))
ax.plot(f3.index, f3["sales"], color=NAVY, lw=2.2, label="Actual")
ax.plot(f3.index, f3[best], color=GOLD, lw=2, label=LABEL[best].replace("\n", " "))
ax.plot(f3.index, f3["naive"], color=COMPARE, lw=1.5, ls="--", label="Baseline")
ax.yaxis.set_major_formatter(money)
ax.legend(frameon=False, ncol=3, loc="upper left")
fw = acc[(acc.fold == str(bt.fold.max())) & (acc.model == best)]["WAPE"].iloc[0]
ax.set_title(f"Backtest, 20 Nov - 31 Dec 2025 (Thanksgiving and Christmas): chain error {fw:.1%}")
save(fig, "chart_backtest_holiday.png")

# 3. 2026 forecast with range ------------------------------------------------------
hist = daily[(daily.is_future == 0) & (daily.date >= "2025-10-01")].groupby("date")["sales"].sum()
hist = hist[hist > 0]
f = fc.groupby("date")[["forecast", "p10", "p90"]].sum()
f = f[f["forecast"] > 0]
ly = daily[daily.is_future == 0].groupby("date")["sales"].sum()
ly.index = ly.index + pd.Timedelta(days=365)       # same calendar dates last year
ly = ly.reindex(fc.groupby("date")["forecast"].sum().index)
fig, ax = plt.subplots(figsize=(10, 3.8))
ax.plot(hist.index, hist.values, color=NAVY, lw=1.6, label="Actual 2025")
ax.fill_between(f.index, f["p10"], f["p90"], color=GOLD, alpha=0.2, label="P10-P90 range")
ax.plot(f.index, f["forecast"], color=GOLD, lw=2.2, label="Forecast")
ax.yaxis.set_major_formatter(money)
ax.legend(frameon=False, ncol=3, loc="upper left", fontsize=9)
chg = fc["forecast"].sum() / ly.sum() - 1
ax.set_title(f"6-week forecast: ${fc['forecast'].sum() / 1e6:.1f}M for 1 Jan - 11 Feb 2026 ({chg:+.1%} vs the same dates in 2025)")
save(fig, "chart_forecast_2026.png")

# 4. drivers: estimated vs true ------------------------------------------------------
d = drv[drv["effect"] != "Extra promo lift, extended assortment"].iloc[::-1].reset_index(drop=True)
fig, ax = plt.subplots(figsize=(9, 5.6))
y = range(len(d))
ax.errorbar(d["estimated"], y, xerr=[(d["estimated"] - d["ci_low"]).fillna(0), (d["ci_high"] - d["estimated"]).fillna(0)],
            fmt="o", color=PRIMARY, ms=6, capsize=3, label="Estimated (95% CI)")
ax.scatter(d["true"], y, marker="|", s=220, color=BAD, lw=2.5, label="True simulated effect", zorder=3)
ax.axvline(0, color="#94A3B8", lw=0.8)
ax.set_yticks(list(y), d["effect"], fontsize=9)
ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
ax.legend(frameon=False, loc="lower right")
ax.set_title("What moves daily sales: regression estimates land on the true effects")
save(fig, "chart_drivers.png")

# 5. competitor hit vs distance ---------------------------------------------------------
fig, ax = plt.subplots(figsize=(7.5, 3.8))
ax.scatter(comp["new_competitor_distance_m"], comp["estimated_hit"], s=70, color=PRIMARY, label="Estimated", zorder=3)
ax.scatter(comp["new_competitor_distance_m"], comp["true_hit"], s=40, facecolors="none", edgecolors=BAD,
           label="True", zorder=3)
ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
ax.set_xlabel("Distance to the new competitor (m)")
ax.set_ylabel("Sales lost")
ax.legend(frameon=False)
ax.set_title(f"A new competitor costs {comp['estimated_hit'].mean():.0%} of sales on average; closer hurts more")
save(fig, "chart_competitor.png")

# 6. weekly chain sales history ------------------------------------------------------------
w = daily[daily.is_future == 0].set_index("date")["sales"].resample("W-SUN").sum()
w = w[w.index <= "2025-12-28"]
fig, ax = plt.subplots(figsize=(10, 3.4))
ax.plot(w.index, w.values, color=PRIMARY, lw=1.8)
ax.yaxis.set_major_formatter(money)
yearly = daily[daily.is_future == 0].groupby(daily.date.dt.year)["sales"].sum()
ax.set_title(f"Weekly chain sales 2023-2025: ${yearly.sum() / 1e6:.0f}M in total, December peaks every year")
save(fig, "chart_weekly_sales.png")
