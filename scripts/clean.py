"""
Corvane Drugstores: clean the raw sales export and build model-ready features.

Input : data_raw/stores.csv, sales.csv, future_calendar.csv
Output: data_clean/stores.csv, daily.csv (history + 2026 calendar, one row per store-day),
        data_quality_log.csv
Run   : python scripts/clean.py   (from the project root)
"""
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW, OUT = ROOT / "data_raw", ROOT / "data_clean"
OUT.mkdir(exist_ok=True)
log = []


def note(table, check, n, action):
    log.append({"table": table, "check": check, "rows_affected": int(n), "action": action})
    print(f"[DQ] {table:<7} {check}: {n:,} -> {action}")


stores = pd.read_csv(RAW / "stores.csv")
sales = pd.read_csv(RAW / "sales.csv")
future = pd.read_csv(RAW / "future_calendar.csv")
note("stores", "rows loaded", len(stores), "none")
note("sales", "rows loaded", len(sales), "none")

# ---- stores -----------------------------------------------------------------
fixed = stores["format"].str.strip().str.title()
note("stores", "format in wrong case", (fixed != stores["format"]).sum(), "title-cased")
stores["format"] = fixed
miss = stores["competition_distance_m"].isna()
note("stores", "missing competition distance", miss.sum(), "filled with the median of the same region, flagged")
stores["competition_distance_imputed"] = miss.astype(int)
stores["competition_distance_m"] = stores.groupby("region")["competition_distance_m"] \
    .transform(lambda s: s.fillna(s.median()))
stores["competitor_opened"] = pd.to_datetime(stores["competitor_opened"])
stores["promo2_since"] = pd.to_datetime(stores["promo2_since"])

# ---- sales history ------------------------------------------------------------
iso = pd.to_datetime(sales["date"], format="%Y-%m-%d", errors="coerce")
us = pd.to_datetime(sales["date"], format="%m/%d/%Y", errors="coerce")
note("sales", "dates in MM/DD/YYYY format", (iso.isna() & us.notna()).sum(), "parsed and standardised")
sales["date"] = iso.fillna(us)
note("sales", "unparseable dates", sales["date"].isna().sum(), "checked")
d = sales.duplicated()
note("sales", "duplicated export rows", d.sum(), "dropped")
sales = sales[~d]
note("sales", "duplicate store-date keys", sales.duplicated(["store_id", "date"]).sum(), "checked")
neg = sales["sales"] < 0
note("sales", "negative sales (sign typo)", neg.sum(), "sign corrected")
sales.loc[neg, "sales"] = sales.loc[neg, "sales"].abs()
outage = (sales["open"] == 1) & (sales["sales"] == 0)
note("sales", "open days with zero sales (POS outage)", outage.sum(),
     "kept, flagged is_outage; excluded from training and accuracy")
sales["is_outage"] = outage.astype(int)
note("sales", "closed days", (sales["open"] == 0).sum(), "kept; forecast is 0 when closed")
expected = pd.MultiIndex.from_product([stores.store_id, pd.date_range("2023-01-01", "2025-12-31")])
note("sales", "missing store-days", len(expected.difference(sales.set_index(["store_id", "date"]).index)),
     "checked")

future["date"] = pd.to_datetime(future["date"])
future["sales"] = np.nan
future["customers"] = np.nan
future["is_outage"] = 0
daily = pd.concat([sales.assign(is_future=0), future.assign(is_future=1)], ignore_index=True)
daily = daily.sort_values(["store_id", "date"]).reset_index(drop=True)

# ---- features -------------------------------------------------------------------
daily = daily.merge(stores[["store_id", "format", "region", "assortment", "sq_ft", "competition_distance_m",
                            "promo2", "promo2_since", "competitor_opened", "new_competitor_distance_m"]],
                    on="store_id", how="left")
dt = daily["date"]
daily["dow"] = dt.dt.day_of_week                     # Mon=0
daily["day_of_month"] = dt.dt.day
daily["month"] = dt.dt.month
daily["year"] = dt.dt.year
daily["week_of_year"] = dt.dt.isocalendar().week.astype(int)
daily["day_of_year"] = dt.dt.day_of_year
daily["payday"] = daily["day_of_month"].isin([1, 2, 3, 15, 16]).astype(int)
daily["promo2_active"] = ((daily["promo2"] == 1) & (dt >= daily["promo2_since"])).astype(int)
days_since = (dt - daily["competitor_opened"]).dt.days
daily["competitor_active"] = (days_since >= 0).astype(int)
daily["days_since_competitor"] = days_since.clip(lower=0).fillna(0).clip(upper=120).where(days_since >= 0, 0)

closed_hol = sorted(daily.loc[daily["holiday_name"].isin(["New Year's Day", "Thanksgiving", "Christmas Day"]),
                              "date"].unique())
cal = pd.DataFrame({"date": pd.date_range("2023-01-01", "2026-02-11")})
cal["pre_holiday_1"] = cal["date"].isin([h - pd.Timedelta(days=1) for h in closed_hol]).astype(int)
cal["pre_holiday_2"] = cal["date"].isin([h - pd.Timedelta(days=2) for h in closed_hol]).astype(int)
daily = daily.merge(cal, on="date", how="left")
daily["open_holiday"] = ((daily["state_holiday"] == 1) & (daily["open"] == 1)).astype(int)
daily["holiday_name"] = daily["holiday_name"].fillna("")
# refurbishment closures: 7+ consecutive closed non-holiday days (a normal week is never fully closed)
cl = (daily["open"] == 0) & (daily["state_holiday"] == 0)
run = ((cl != cl.shift()) | (daily["store_id"] != daily["store_id"].shift())).cumsum()
run_len = cl.groupby([daily["store_id"], run]).transform("sum")
daily["refurb_closed"] = (cl & (run_len >= 7)).astype(int)
note("sales", "refurbishment closure days (7+ consecutive closed days)", daily["refurb_closed"].sum(),
     "flagged refurb_closed")
reopen = daily[daily["refurb_closed"] == 1].groupby("store_id")["date"].max() + pd.Timedelta(days=1)
since_reopen = (daily["date"] - daily["store_id"].map(reopen)).dt.days
daily["post_refurb"] = since_reopen.between(0, 59).astype(int)
daily["usable"] = ((daily["open"] == 1) & (daily["is_outage"] == 0) & (daily["is_future"] == 0)).astype(int)

keep = ["store_id", "date", "is_future", "open", "promo", "state_holiday", "holiday_name", "school_holiday",
        "sales", "customers", "is_outage", "usable", "format", "region", "assortment", "sq_ft",
        "competition_distance_m", "dow", "day_of_month", "month", "year", "week_of_year", "day_of_year",
        "payday", "promo2_active", "competitor_active", "days_since_competitor", "new_competitor_distance_m",
        "pre_holiday_1", "pre_holiday_2", "open_holiday", "refurb_closed", "post_refurb"]
daily[keep].to_csv(OUT / "daily.csv", index=False, date_format="%Y-%m-%d")
stores.to_csv(OUT / "stores.csv", index=False, date_format="%Y-%m-%d")
pd.DataFrame(log).to_csv(OUT / "data_quality_log.csv", index=False)
h = daily[daily.is_future == 0]
print(f"\nwrote data_clean/daily.csv  ({len(daily):,} rows: {len(h):,} history, {daily.is_future.sum():,} future)")
print(f"history sales: ${h.sales.sum():,.2f}   usable training days: {h.usable.sum():,}")
