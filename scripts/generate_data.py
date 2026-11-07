"""
Generate a synthetic daily sales dataset for "Corvane Drugstores", a fictional US chain of
60 drugstores (Jan 2023 to Dec 2025), plus the known calendar for the 6 forecast weeks
(1 Jan to 11 Feb 2026).

The data is simulated, not real. Every effect is written down here, so the forecasting and
driver analysis can be checked against the truth (see TRUE_EFFECTS at the bottom):
  * three store formats with different size, Sunday trading and promo response
  * yearly seasonality (December gifting, Jan-Feb cold & flu season, quieter summer)
  * weekday pattern, payday bump (1st-3rd and 15th-16th of the month)
  * chain promotions (Mon-Fri promo weeks) and a loyalty programme ("promo2") from mid 2024
  * public holidays (closed on New Year's Day, Thanksgiving, Christmas; quieter on others),
    pre-holiday rush, school holidays by region
  * new competitors opening near 12 stores, refurbishment closures with a reopening bump
  * 4% a year underlying growth plus store-level drift and day-to-day noise
The raw files also contain realistic mess (inconsistent codes, duplicate rows, POS outages
recorded as zero sales, a few typos) for scripts/clean.py to fix.

Output: data_raw/stores.csv, data_raw/sales.csv, data_raw/future_calendar.csv
Run   : python scripts/generate_data.py   (from the project root)
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd

SEED = 7
rng = np.random.default_rng(SEED)
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data_raw"
RAW.mkdir(exist_ok=True)

HIST_START, HIST_END = pd.Timestamp("2023-01-01"), pd.Timestamp("2025-12-31")
FUT_END = pd.Timestamp("2026-02-11")
N_STORES = 60

# ---------------------------------------------------------------- stores
REGIONS = {"Northeast": ["Boston", "Hartford", "Providence", "Albany", "Worcester"],
           "Southeast": ["Atlanta", "Charlotte", "Raleigh", "Tampa", "Orlando", "Nashville"],
           "Midwest": ["Columbus", "Indianapolis", "Milwaukee", "Madison", "Des Moines"],
           "West": ["Denver", "Phoenix", "Sacramento", "Portland", "Boise", "Salt Lake City"]}
FORMAT = {  # base daily sales, Sunday factor, promo lift, avg basket
    "Neighborhood": dict(base=9000, sunday=0.62, lift=0.18, basket=27.0),
    "Flagship": dict(base=17500, sunday=0.78, lift=0.12, basket=34.0),
    "Express": dict(base=5200, sunday=0.0, lift=0.25, basket=19.0),    # closed on Sundays
}
fmt = rng.choice(list(FORMAT), N_STORES, p=[0.62, 0.12, 0.26])
region = rng.choice(list(REGIONS), N_STORES, p=[0.24, 0.30, 0.22, 0.24])
stores = pd.DataFrame({
    "store_id": np.arange(1, N_STORES + 1),
    "store_name": [f"{REGIONS[r][rng.integers(len(REGIONS[r]))]} #{i + 1:02d}" for i, r in enumerate(region)],
    "format": fmt, "region": region,
    "assortment": rng.choice(["Basic", "Extended"], N_STORES, p=[0.55, 0.45]),
    "sq_ft": 0, "competition_distance_m": np.round(rng.lognormal(7.2, 0.9, N_STORES), -1),
    "opened_year": rng.integers(1998, 2021, N_STORES),
})
stores["sq_ft"] = stores["format"].map({"Neighborhood": 9500, "Flagship": 17000, "Express": 4200}) \
    * rng.uniform(0.85, 1.15, N_STORES)
stores["sq_ft"] = stores["sq_ft"].round(-2).astype(int)
store_mult = rng.lognormal(0, 0.18, N_STORES)                      # location quality
store_trend = rng.normal(0.04, 0.025, N_STORES)                    # yearly growth per store

# loyalty programme (promo2) rolled out to 40% of stores from 1 Jul 2024
promo2 = rng.random(N_STORES) < 0.4
stores["promo2"] = promo2.astype(int)
stores["promo2_since"] = np.where(promo2, "2024-07-01", "")

# new competitor near 12 stores, opening between Mar 2024 and Sep 2025
comp_stores = rng.choice(N_STORES, 12, replace=False)
comp_open = {int(s): pd.Timestamp("2024-03-01") + pd.Timedelta(days=int(rng.integers(0, 550)))
             for s in comp_stores}
comp_new_dist = {s: float(np.round(rng.uniform(250, 1500), -1)) for s in comp_open}
# refurbishment: 4 stores closed 14-28 days
refurb_stores = rng.choice([s for s in range(N_STORES) if s not in comp_open], 4, replace=False)
refurb = {int(s): (pd.Timestamp("2024-01-15") + pd.Timedelta(days=int(rng.integers(0, 600))),
                   int(rng.integers(14, 29))) for s in refurb_stores}

# ---------------------------------------------------------------- calendar
days = pd.date_range(HIST_START, FUT_END, freq="D")


def us_holidays(year):
    def nth(month, weekday, n):
        d = pd.Timestamp(year, month, 1)
        d += pd.Timedelta(days=(weekday - d.weekday()) % 7)
        return d + pd.Timedelta(weeks=n - 1)

    def last(month, weekday):
        d = pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0)
        return d - pd.Timedelta(days=(d.weekday() - weekday) % 7)

    return {pd.Timestamp(year, 1, 1): "New Year's Day", nth(1, 0, 3): "MLK Day", nth(2, 0, 3): "Presidents Day",
            last(5, 0): "Memorial Day", pd.Timestamp(year, 7, 4): "Independence Day", nth(9, 0, 1): "Labor Day",
            nth(11, 3, 4): "Thanksgiving", pd.Timestamp(year, 12, 25): "Christmas Day"}


HOL = {}
for y in range(2023, 2027):
    HOL.update(us_holidays(y))
CLOSED_HOL = {"New Year's Day", "Thanksgiving", "Christmas Day"}

cal = pd.DataFrame({"date": days})
cal["dow"] = cal.date.dt.day_of_week                 # Mon=0
cal["holiday_name"] = cal.date.map(HOL).fillna("")
cal["state_holiday"] = (cal.holiday_name != "").astype(int)
# chain promo weeks: ~35% of weeks, Mon-Fri; always the week before Thanksgiving and early December
weeks = cal.date.dt.to_period("W-SUN")
uw = weeks.unique()
promo_week = {w: rng.random() < 0.33 for w in uw}
for y in (2023, 2024, 2025):
    tg = [d for d, n in HOL.items() if n == "Thanksgiving" and d.year == y][0]
    promo_week[(tg - pd.Timedelta(days=7)).to_period("W-SUN")] = True
    promo_week[pd.Timestamp(y, 12, 4).to_period("W-SUN")] = True
for w in pd.date_range("2026-01-01", FUT_END, freq="D").to_period("W-SUN").unique():  # 2026 plan
    promo_week[w] = w.start_time in (pd.Timestamp("2026-01-12"), pd.Timestamp("2026-01-26"),
                                     pd.Timestamp("2026-02-09"))
cal["promo"] = [int(promo_week[w] and d < 5) for w, d in zip(weeks, cal.dow)]

# school holidays per region (summer shifted by region, winter break, spring break week)
SPRING = {"Northeast": 16, "Southeast": 11, "Midwest": 12, "West": 13}   # ISO week number
SUMMER = {"Northeast": ("06-24", "09-03"), "Southeast": ("05-27", "08-08"),
          "Midwest": ("06-05", "08-20"), "West": ("06-12", "08-25")}


def school(date, reg):
    md = date.strftime("%m-%d")
    s0, s1 = SUMMER[reg]
    return int(s0 <= md <= s1 or md >= "12-21" or md <= "01-02" or date.isocalendar().week == SPRING[reg])


# ---------------------------------------------------------------- sales
SEASON = np.array([1.06, 1.05, 1.00, 0.98, 1.00, 0.97, 0.95, 0.96, 0.99, 1.00, 1.04, 1.22])  # by month
DOW = np.array([1.04, 0.98, 0.97, 0.99, 1.06, 1.12, 1.00])          # Sunday handled by format
rows = []
t_years = ((cal.date - HIST_START).dt.days / 365.25).to_numpy()
dom = cal.date.dt.day.to_numpy()
month = cal.date.dt.month.to_numpy()
payday = np.where(np.isin(dom, [1, 2, 3, 15, 16]), 1.06, 1.0)
next_hol = {}
hol_dates = sorted(d for d, n in HOL.items() if n in CLOSED_HOL)
pre_hol = np.ones(len(cal))
for hd in hol_dates:                                                   # rush before closed holidays
    for k, bump in [(1, 1.18), (2, 1.08)]:
        idx = np.where(cal.date == hd - pd.Timedelta(days=k))[0]
        if len(idx):
            pre_hol[idx[0]] = bump
open_hol_factor = np.where((cal.state_holiday == 1) & ~cal.holiday_name.isin(CLOSED_HOL), 0.82, 1.0)

for s in range(N_STORES):
    st = stores.iloc[s]
    f = FORMAT[st.format]
    reg = st.region
    sch = np.array([school(d, reg) for d in cal.date])
    base = f["base"] * store_mult[s] * (1 + store_trend[s]) ** t_years
    dowf = DOW[cal.dow.to_numpy()].copy()
    dowf[cal.dow.to_numpy() == 6] = f["sunday"]
    lift = f["lift"] + (0.03 if st.assortment == "Extended" else 0.0)
    promo_f = 1 + lift * cal.promo.to_numpy()
    p2 = np.where(promo2[s] & (cal.date >= "2024-07-01").to_numpy(), 1.04, 1.0)
    # school holidays: more footfall for Neighborhood stores, less for Express (commuter locations)
    sch_f = 1 + sch * {"Neighborhood": 0.05, "Flagship": 0.03, "Express": -0.06}[st.format]
    comp_f = np.ones(len(cal))
    if s in comp_open:
        d0 = comp_open[s]
        size = 0.06 + 0.10 * (1 - min(comp_new_dist[s], 1500) / 1500)          # closer = bigger hit
        ramp = np.clip((cal.date - d0).dt.days.to_numpy() / 60, 0, 1)            # settles over 2 months
        comp_f = 1 - size * ramp
    open_ = np.ones(len(cal), dtype=int)
    open_[cal.holiday_name.isin(CLOSED_HOL).to_numpy()] = 0
    if f["sunday"] == 0:
        open_[cal.dow.to_numpy() == 6] = 0
    refurb_f = np.ones(len(cal))
    if s in refurb:
        r0, dur = refurb[s]
        closed = ((cal.date >= r0) & (cal.date < r0 + pd.Timedelta(days=dur))).to_numpy()
        open_[closed] = 0
        after = ((cal.date >= r0 + pd.Timedelta(days=dur)) &
                 (cal.date < r0 + pd.Timedelta(days=dur + 60))).to_numpy()
        refurb_f[after] = 1.06
    noise = rng.lognormal(0, 0.07, len(cal))
    sales = (base * SEASON[month - 1] * dowf * payday * promo_f * p2 * sch_f * comp_f * refurb_f
             * pre_hol * open_hol_factor * noise) * open_
    basket = f["basket"] * (1 + 0.06 * cal.promo.to_numpy() * -1 + 0.04 * (month == 12)) * rng.lognormal(0, 0.05, len(cal))
    customers = np.where(open_ == 1, np.round(sales / basket), 0)
    rows.append(pd.DataFrame({
        "store_id": st.store_id, "date": cal.date, "day_of_week": cal.dow + 1, "open": open_,
        "promo": cal.promo * open_, "state_holiday": cal.state_holiday, "holiday_name": cal.holiday_name,
        "school_holiday": sch, "sales": np.round(sales, 2), "customers": customers.astype(int)}))

daily = pd.concat(rows, ignore_index=True)
hist = daily[daily.date <= HIST_END].copy()
fut = daily[daily.date > HIST_END].drop(columns=["sales", "customers"]).copy()

# competitor info as a store attribute (as a real store master would hold it)
stores["competitor_opened"] = stores.store_id.map(lambda i: comp_open[i - 1].strftime("%Y-%m-%d")
                                                  if i - 1 in comp_open else "")
stores["new_competitor_distance_m"] = stores.store_id.map(lambda i: comp_new_dist.get(i - 1, np.nan))

# ---------------------------------------------------------------- real-world mess
n = len(hist)
outage = hist.index[(hist.open == 1) & (rng.random(n) < 0.0015)]          # POS outage: zero sales recorded
hist.loc[outage, ["sales", "customers"]] = 0
typo = hist.index[(hist.open == 1) & (rng.random(n) < 0.0002)]            # sign typo
hist.loc[typo, "sales"] *= -1
dup = hist.sample(frac=0.002, random_state=SEED)
hist = pd.concat([hist, dup]).sort_values(["store_id", "date"]).reset_index(drop=True)
hist["date"] = hist.date.dt.strftime("%Y-%m-%d")
m = rng.random(len(hist)) < 0.01                                         # some rows in US date format
hist.loc[m, "date"] = pd.to_datetime(hist.loc[m, "date"]).dt.strftime("%m/%d/%Y")
stores_raw = stores.copy()
upper = rng.choice(N_STORES, 5, replace=False)                        # same codes, wrong case
stores_raw.loc[upper, "format"] = stores_raw.loc[upper, "format"].str.upper()
stores_raw.loc[rng.choice(N_STORES, 3, replace=False), "competition_distance_m"] = np.nan

stores_raw.to_csv(RAW / "stores.csv", index=False)
hist.to_csv(RAW / "sales.csv", index=False)
fut.assign(date=fut.date.dt.strftime("%Y-%m-%d")).to_csv(RAW / "future_calendar.csv", index=False)

TRUE_EFFECTS = {
    "promo_lift_by_format": {k: v["lift"] for k, v in FORMAT.items()},
    "extended_assortment_extra_lift": 0.03,
    "loyalty_programme_lift": 0.04,
    "payday_lift": 0.06,
    "pre_holiday_rush": {"day_before": 0.18, "two_days_before": 0.08},
    "open_holiday_factor": 0.82,
    "competitor_hit_range": "6% (1.5 km away) to 16% (next door), phased in over 60 days",
    "competitor_hit_by_store": {int(s + 1): round(0.06 + 0.10 * (1 - min(comp_new_dist[s], 1500) / 1500), 3)
                                for s in comp_open},
    "school_holiday": {"Neighborhood": 0.05, "Flagship": 0.03, "Express": -0.06},
    "refurb_reopening_bump": 0.06,
    "noise_sd_log": 0.07,
}
(RAW / "true_effects.json").write_text(json.dumps(TRUE_EFFECTS, indent=2))
print(f"stores: {len(stores_raw)}  history rows: {len(hist):,}  future rows: {len(fut):,}")
print(f"history sales total: ${daily[daily.date <= HIST_END].sales.sum():,.0f}")
