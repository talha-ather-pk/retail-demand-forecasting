"""
Corvane Drugstores: what drives daily sales? Effect sizes from a fixed-effects regression.

Model (log sales, open days only):
    log(sales) = store x weekday effect + store trend + month effect
                 + promo x format + promo x extended assortment + school holiday x format
                 + payday + pre-holiday (1 and 2 days) + open holiday + loyalty programme
                 + post-refurbishment + new competitor (per affected store, phased in) + error
Store x weekday effects are removed by demeaning (within transformation), the rest is OLS
with heteroskedasticity-robust standard errors.

Because the data is synthetic, every estimate is compared with the true value used by the
generator (data_raw/true_effects.json). Close agreement shows the method recovers real effects.

Input : data_clean/daily.csv, data_raw/true_effects.json
Output: data_clean/driver_effects.csv, data_clean/competitor_effects.csv
Run   : python scripts/drivers.py   (from the project root)
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import statsmodels.api as sm

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data_clean"
truth = json.loads((ROOT / "data_raw" / "true_effects.json").read_text())

d = pd.read_csv(OUT / "daily.csv", parse_dates=["date"])
d = d[d["usable"] == 1].copy()
d["y"] = np.log(d["sales"])
d["t"] = (d["date"] - d["date"].min()).dt.days / 365.25
d["competitor_ramp"] = (d["days_since_competitor"] / 60).clip(upper=1) * d["competitor_active"]
FORMATS = ["Neighborhood", "Flagship", "Express"]

X = pd.DataFrame(index=d.index)
for f in FORMATS:
    X[f"promo_{f}"] = d["promo"] * (d["format"] == f)
    X[f"school_{f}"] = d["school_holiday"] * (d["format"] == f)
X["promo_extended"] = d["promo"] * (d["assortment"] == "Extended")
for c in ["payday", "pre_holiday_1", "pre_holiday_2", "open_holiday", "promo2_active", "post_refurb"]:
    X[c] = d[c]
for m in range(2, 13):
    X[f"month_{m}"] = (d["month"] == m).astype(float)
comp_stores = sorted(d.loc[d["competitor_active"] == 1, "store_id"].unique())
for s in comp_stores:
    X[f"comp_{s}"] = d["competitor_ramp"] * (d["store_id"] == s)
for s in sorted(d["store_id"].unique()):
    X[f"trend_{s}"] = d["t"] * (d["store_id"] == s)

# within transformation: remove store x weekday means from y and every regressor
grp = [d["store_id"], d["dow"]]
yw = d["y"] - d.groupby(grp)["y"].transform("mean")
Xw = X.astype(float) - X.astype(float).groupby(grp).transform("mean")
Xw = Xw.loc[:, Xw.abs().sum() > 0]
res = sm.OLS(yw, Xw).fit(cov_type="HC1")
b, se = res.params, res.bse
print(f"OLS on {len(d):,} store-days, {Xw.shape[1]} regressors, within R² = {res.rsquared:.3f}")


def pct(coef):
    return float(np.exp(coef) - 1)


rows = []


def add(effect, coef_name, true_value, group):
    est = pct(b[coef_name])
    lo, hi = pct(b[coef_name] - 1.96 * se[coef_name]), pct(b[coef_name] + 1.96 * se[coef_name])
    rows.append({"group": group, "effect": effect, "estimated": est, "ci_low": lo, "ci_high": hi,
                 "true": true_value})


for f in FORMATS:
    add(f"Promotion lift, {f} (basic assortment)", f"promo_{f}", truth["promo_lift_by_format"][f], "Promotions")
ext = np.mean([np.exp(b[f"promo_{f}"] + b["promo_extended"]) - np.exp(b[f"promo_{f}"]) for f in FORMATS])
rows.append({"group": "Promotions", "effect": "Extra promo lift, extended assortment", "estimated": float(ext),
             "ci_low": np.nan, "ci_high": np.nan, "true": truth["extended_assortment_extra_lift"]})
add("Loyalty programme (promo2)", "promo2_active", truth["loyalty_programme_lift"], "Promotions")
add("Payday (1st-3rd, 15th-16th)", "payday", truth["payday_lift"], "Calendar")
add("Day before a closed holiday", "pre_holiday_1", truth["pre_holiday_rush"]["day_before"], "Calendar")
add("Two days before a closed holiday", "pre_holiday_2", truth["pre_holiday_rush"]["two_days_before"], "Calendar")
add("Open public holiday", "open_holiday", truth["open_holiday_factor"] - 1, "Calendar")
for f in FORMATS:
    add(f"School holiday, {f}", f"school_{f}", truth["school_holiday"][f], "Calendar")
add("First 60 days after refurbishment", "post_refurb", truth["refurb_reopening_bump"], "Stores")
eff = pd.DataFrame(rows)

comp = []
stores = pd.read_csv(OUT / "stores.csv")
for s in comp_stores:
    st = stores[stores.store_id == s].iloc[0]
    comp.append({"store_id": s, "format": st.format, "competitor_opened": st.competitor_opened,
                 "new_competitor_distance_m": st.new_competitor_distance_m,
                 "estimated_hit": -pct(b[f"comp_{s}"]), "true_hit": truth["competitor_hit_by_store"][str(s)]})
comp = pd.DataFrame(comp).sort_values("new_competitor_distance_m")
rows_c = {"group": "Competition", "effect": "New competitor nearby (average sales hit)",
          "estimated": -comp["estimated_hit"].mean(), "ci_low": np.nan, "ci_high": np.nan,
          "true": -comp["true_hit"].mean()}
eff = pd.concat([eff, pd.DataFrame([rows_c])], ignore_index=True)

naive_promo = d[d.promo == 1]["sales"].mean() / d[d.promo == 0]["sales"].mean() - 1
eff.attrs["naive"] = naive_promo
eff.to_csv(OUT / "driver_effects.csv", index=False)
comp.to_csv(OUT / "competitor_effects.csv", index=False)
pd.set_option("display.width", 160)
show = eff.assign(**{c: (eff[c] * 100).round(1) for c in ["estimated", "ci_low", "ci_high", "true"]})
print(show[["effect", "estimated", "ci_low", "ci_high", "true"]].to_string(index=False))
print(f"\nNaive promo comparison (promo days vs non-promo days, no controls): {naive_promo:+.1%}")
print("\nCompetitor hit by store (closest first):")
print(comp.assign(estimated_hit=lambda x: (x.estimated_hit * 100).round(1),
                  true_hit=lambda x: (x.true_hit * 100).round(1)).to_string(index=False))
