"""
Corvane Drugstores: 6-week daily sales forecast per store.

Models
  1. Seasonal naive : same weekday 52 weeks earlier (the "do nothing" baseline)
  2. Prophet        : one model per store, log sales, yearly + weekly seasonality,
                      promo / holiday / school / payday / competitor / loyalty regressors
  3. Gradient boost : one global HistGradientBoosting model on log sales with store,
                      calendar, promo, holiday and competitor features + lagged levels
  4. Ensemble       : average of Prophet and gradient boosting
Validation: rolling-origin backtest, three 42-day windows (Jun-Jul, Sep-Oct, Nov-Dec 2025).
Every feature uses only data available at the forecast origin (lags of 42+ days).
Final: refit on all history to 31 Dec 2025 and forecast 1 Jan - 11 Feb 2026 with P10/P90.

Input : data_clean/daily.csv
Output: data_clean/backtest_predictions.csv, accuracy_by_model.csv, accuracy_by_store.csv,
        accuracy_by_week.csv, forecast_2026.csv, feature_importance.csv
Run   : python scripts/forecast.py   (from the project root; about 10 minutes, Prophet is the slow part)
"""
from pathlib import Path
import logging
import warnings
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance

warnings.filterwarnings("ignore")
logging.getLogger("cmdstanpy").setLevel(logging.ERROR)
logging.getLogger("prophet").setLevel(logging.ERROR)
from prophet import Prophet  # noqa: E402
logging.getLogger("cmdstanpy").disabled = True   # silence per-fit progress messages

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data_clean"
H = 42
ORIGINS = [pd.Timestamp("2025-05-31"), pd.Timestamp("2025-08-31"), pd.Timestamp("2025-11-19")]
FINAL_ORIGIN = pd.Timestamp("2025-12-31")
SEED = 42

df = pd.read_csv(OUT / "daily.csv", parse_dates=["date"])
df = df.sort_values(["store_id", "date"]).reset_index(drop=True)
df["log_sales"] = np.where(df["usable"] == 1, np.log1p(df["sales"]), np.nan)
df["competitor_ramp"] = (df["days_since_competitor"] / 60).clip(upper=1) * df["competitor_active"]

# lagged features (always 42+ days back, so they are known at the forecast origin)
g = df.groupby("store_id")["log_sales"]
df["lag_364"] = g.shift(364)
df["level_lag42"] = g.transform(lambda s: s.shift(42).rolling(56, min_periods=20).mean())
df["level_lag42_dow"] = df.groupby(["store_id", "dow"])["log_sales"].transform(
    lambda s: s.shift(6).rolling(8, min_periods=3).mean())   # same weekday, 6+ weeks back

CAT = ["store_id", "format", "region", "assortment"]
NUM = ["sq_ft", "competition_distance_m", "dow", "day_of_month", "month", "week_of_year", "day_of_year",
       "promo", "state_holiday", "school_holiday", "payday", "promo2_active", "competitor_active",
       "competitor_ramp", "pre_holiday_1", "pre_holiday_2", "open_holiday", "post_refurb",
       "lag_364", "level_lag42", "level_lag42_dow", "store_dow_mean"]
FEATURES = CAT + NUM
REGRESSORS = ["promo", "school_holiday", "payday", "promo2_active", "competitor_ramp", "pre_holiday_1",
              "pre_holiday_2", "open_holiday", "post_refurb"]
for c in ["format", "region", "assortment"]:
    df[c] = df[c].astype("category").cat.codes


def window(origin):
    test = (df["date"] > origin) & (df["date"] <= origin + pd.Timedelta(days=H))
    train = (df["date"] <= origin) & (df["usable"] == 1)
    return train, test


def add_store_dow_mean(train_mask):
    m = df[train_mask].groupby(["store_id", "dow"])["log_sales"].mean()
    df["store_dow_mean"] = pd.MultiIndex.from_frame(df[["store_id", "dow"]]).map(m.to_dict().get)
    df["store_dow_mean"] = df["store_dow_mean"].astype(float)


def gbm(loss="squared_error", quantile=None):
    kw = dict(loss=loss, learning_rate=0.05, max_iter=700, max_leaf_nodes=48, min_samples_leaf=40,
              l2_regularization=1.0, categorical_features=[FEATURES.index(c) for c in CAT], random_state=SEED)
    if quantile is not None:
        kw["quantile"] = quantile
    return HistGradientBoostingRegressor(**kw)


def fit_gbm(train_mask, test_mask, quantiles=False):
    add_store_dow_mean(train_mask)
    X, y = df.loc[train_mask, FEATURES], df.loc[train_mask, "log_sales"]
    model = gbm().fit(X, y)
    smear = np.mean(np.exp(y - model.predict(X)))                  # log back-transform bias correction
    Xt = df.loc[test_mask, FEATURES]
    out = {"gbm": np.expm1(model.predict(Xt)) * smear}
    if quantiles:
        out["p10"] = np.expm1(gbm("quantile", 0.10).fit(X, y).predict(Xt))
        out["p90"] = np.expm1(gbm("quantile", 0.90).fit(X, y).predict(Xt))
    return out, model


def fit_prophet(train_mask, test_mask):
    preds = pd.Series(np.nan, index=df.index[test_mask])
    for sid, tr in df[train_mask].groupby("store_id"):
        m = Prophet(yearly_seasonality=10, weekly_seasonality=True, daily_seasonality=False,
                    changepoint_prior_scale=0.05, seasonality_prior_scale=5)
        for r in REGRESSORS:
            m.add_regressor(r)
        hist = tr.rename(columns={"date": "ds", "log_sales": "y"})[["ds", "y"] + REGRESSORS]
        m.fit(hist)
        resid = hist["y"] - m.predict(hist)["yhat"].to_numpy()
        smear = np.mean(np.exp(resid))
        te = df[test_mask & (df["store_id"] == sid)]
        fc = m.predict(te.rename(columns={"date": "ds"})[["ds"] + REGRESSORS])
        preds.loc[te.index] = np.expm1(fc["yhat"].to_numpy()) * smear
    return preds.to_numpy()


def naive(test_mask, origin):
    """Same weekday 52 weeks earlier; if that day was closed, the store's recent same-weekday mean."""
    lag = df.groupby("store_id")["sales"].shift(364).where(
        df.groupby("store_id")["usable"].shift(364) == 1)
    recent = df[(df["date"] <= origin) & (df["date"] > origin - pd.Timedelta(days=56)) & (df["usable"] == 1)] \
        .groupby(["store_id", "dow"])["sales"].mean()
    fb = pd.MultiIndex.from_frame(df[["store_id", "dow"]]).map(recent.to_dict().get).astype(float)
    return lag.fillna(pd.Series(fb, index=df.index))[test_mask].to_numpy()


# ---------------------------------------------------------------- backtest
frames = []
for k, origin in enumerate(ORIGINS, 1):
    train, test = window(origin)
    print(f"fold {k}: origin {origin.date()}  train rows {train.sum():,}  test rows {test.sum():,}")
    g_out, g_model = fit_gbm(train, test)
    p = fit_prophet(train, test)
    t = df.loc[test, ["store_id", "date", "open", "usable", "is_outage", "promo", "state_holiday",
                      "holiday_name", "sales"]].copy()
    t["fold"] = k
    t["origin"] = origin
    closed = t["open"].to_numpy() == 0
    for name, v in [("naive", naive(test, origin)), ("prophet", p), ("gbm", g_out["gbm"])]:
        t[name] = np.where(closed, 0.0, v)
    t["ensemble"] = (t["prophet"] + t["gbm"]) / 2
    frames.append(t)
bt = pd.concat(frames, ignore_index=True)
MODELS = ["naive", "prophet", "gbm", "ensemble"]


def scores(d):
    d = d[d["usable"] == 1]
    a = d["sales"]
    r = {}
    for mname in MODELS:
        e = d[mname] - a
        r[mname] = {"WAPE": e.abs().sum() / a.sum(), "MAPE": (e.abs() / a).mean(),
                    "RMSE": float(np.sqrt((e ** 2).mean())), "Bias": e.sum() / a.sum()}
    return r


rows = []
for fold, d in list(bt.groupby("fold")) + [("all", bt)]:
    for mname, s in scores(d).items():
        rows.append({"fold": fold, "model": mname, **s})
acc = pd.DataFrame(rows)
acc.to_csv(OUT / "accuracy_by_model.csv", index=False)
summary = acc[acc.fold == "all"].set_index("model")
best = summary["WAPE"].idxmin()
print("\nBacktest accuracy (all 3 folds, open days):")
print(summary.round(4).to_string())
print(f"best model: {best}")

srows = []
for sid, d in bt.groupby("store_id"):
    s = scores(d)
    srows.append({"store_id": sid, **{f"{m}_wape": s[m]["WAPE"] for m in MODELS}})
pd.DataFrame(srows).to_csv(OUT / "accuracy_by_store.csv", index=False)
wk = bt[bt.usable == 1].assign(week=lambda d: d["date"].dt.to_period("W-SUN").dt.start_time)
wk = wk.groupby(["fold", "week"])[["sales"] + MODELS].sum().reset_index()
wk.to_csv(OUT / "accuracy_by_week.csv", index=False, date_format="%Y-%m-%d")
bt.to_csv(OUT / "backtest_predictions.csv", index=False, date_format="%Y-%m-%d")

# ---------------------------------------------------------------- final forecast 2026
train, test = (df["date"] <= FINAL_ORIGIN) & (df["usable"] == 1), df["is_future"] == 1
g_out, g_model = fit_gbm(train, test, quantiles=True)
p = fit_prophet(train, test)
f = df.loc[test, ["store_id", "date", "open", "promo", "state_holiday", "holiday_name", "school_holiday"]].copy()
closed = f["open"].to_numpy() == 0
f["forecast_prophet"] = np.where(closed, 0, p)
f["forecast_gbm"] = np.where(closed, 0, g_out["gbm"])
f["forecast_ensemble"] = (f["forecast_prophet"] + f["forecast_gbm"]) / 2
f["forecast"] = f[f"forecast_{best}"] if best != "naive" else f["forecast_ensemble"]
f["p10"] = np.where(closed, 0, np.minimum(g_out["p10"], f["forecast"]))
f["p90"] = np.where(closed, 0, np.maximum(g_out["p90"], f["forecast"]))
f["model"] = best
f.round(2).to_csv(OUT / "forecast_2026.csv", index=False, date_format="%Y-%m-%d")
print(f"\n2026 forecast ({best}): ${f['forecast'].sum():,.0f} over {f['date'].nunique()} days "
      f"(P10 ${f['p10'].sum():,.0f} - P90 ${f['p90'].sum():,.0f})")

# ---------------------------------------------------------------- what drives the model
last_train, last_test = window(ORIGINS[-1])
add_store_dow_mean(last_train)
_, model = fit_gbm(last_train, last_test)
ev = df[last_test & (df["usable"] == 1)]
pi = permutation_importance(model, ev[FEATURES], ev["log_sales"], n_repeats=5, random_state=SEED,
                            scoring="neg_mean_absolute_error")
imp = pd.DataFrame({"feature": FEATURES, "importance": pi.importances_mean}).sort_values("importance",
                                                                                        ascending=False)
imp.to_csv(OUT / "feature_importance.csv", index=False)
print("\nTop features (permutation importance, fold 3):")
print(imp.head(8).round(4).to_string(index=False))
