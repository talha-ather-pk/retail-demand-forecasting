"""
Corvane Drugstores: build the 6-week forecast workbook for store and finance teams.

Input : data_clean/forecast_2026.csv, daily.csv, stores.csv, accuracy_by_model.csv,
        accuracy_by_store.csv, driver_effects.csv
Output: excel/Corvane_6-week_forecast_2026.xlsx
Run   : python scripts/excel_report.py   (from the project root)
"""
from pathlib import Path
import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

ROOT = Path(__file__).resolve().parents[1]
C = ROOT / "data_clean"
OUT = ROOT / "excel"
OUT.mkdir(exist_ok=True)

NAVY, GOLD, SLATE, LINE, PALE = "0B1F3A", "C8A24A", "64748B", "E6E9F0", "F6F8FB"
H_FONT = Font(name="Segoe UI", bold=True, color="FFFFFF", size=10)
H_FILL = PatternFill("solid", fgColor=NAVY)
BODY = Font(name="Segoe UI", size=10)
THIN = Border(bottom=Side(style="thin", color=LINE))
MONEY, PCT = '"$"#,##0', '0.0%;[Red]-0.0%'

fc = pd.read_csv(C / "forecast_2026.csv", parse_dates=["date"])
daily = pd.read_csv(C / "daily.csv", parse_dates=["date"])
stores = pd.read_csv(C / "stores.csv")
acc = pd.read_csv(C / "accuracy_by_model.csv")
acc_store = pd.read_csv(C / "accuracy_by_store.csv")
drivers = pd.read_csv(C / "driver_effects.csv")
model = fc["model"].iloc[0]
model_label = {"gbm": "Gradient boosting", "prophet": "Prophet", "ensemble": "Ensemble (Prophet + GBM)"}[model]

# last-year actuals on the same calendar dates (365 days earlier): every 7-day block then holds the
# same weekdays, and New Year's Day (closed) lines up with New Year's Day
ly = daily[["store_id", "date", "sales"]].copy()
ly["date"] = ly["date"] + pd.Timedelta(days=365)
fc = fc.merge(ly.rename(columns={"sales": "ly_sales"}), on=["store_id", "date"], how="left")
fc["week"] = ((fc["date"] - fc["date"].min()).dt.days // 7 + 1)
fc = fc.merge(stores[["store_id", "store_name", "format", "region"]], on="store_id")

wb = Workbook()


def header(ws, row, cols, start_col=1):
    for i, c in enumerate(cols):
        cell = ws.cell(row=row, column=start_col + i, value=c)
        cell.font, cell.fill = H_FONT, H_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30


def widths(ws, w):
    for i, v in enumerate(w, 1):
        ws.column_dimensions[get_column_letter(i)].width = v


def title(ws, text, sub):
    ws["A1"] = text
    ws["A1"].font = Font(name="Segoe UI Semibold", size=16, color=NAVY)
    ws["A2"] = sub
    ws["A2"].font = Font(name="Segoe UI", size=10, color=SLATE)
    ws.sheet_view.showGridLines = False


# ---------------------------------------------------------------- Summary
ws = wb.active
ws.title = "Summary"
title(ws, "Corvane Drugstores · 6-week sales forecast",
      f"1 Jan – 11 Feb 2026 · 60 stores · model: {model_label} · synthetic data for portfolio use")
best = acc[(acc.fold == "all") & (acc.model == model)].iloc[0]
naive = acc[(acc.fold == "all") & (acc.model == "naive")].iloc[0]
kpis = [("Forecast sales", fc["forecast"].sum(), MONEY),
        ("Low case (P10)", fc["p10"].sum(), MONEY),
        ("High case (P90)", fc["p90"].sum(), MONEY),
        ("Same weeks last year", fc["ly_sales"].sum(), MONEY),
        ("Change vs last year", fc["forecast"].sum() / fc["ly_sales"].sum() - 1, PCT),
        ("Backtest error (WAPE)", best["WAPE"], "0.0%"),
        ("Baseline error (WAPE)", naive["WAPE"], "0.0%")]
for i, (k, v, f) in enumerate(kpis):
    col = 1 + i
    ws.cell(row=4, column=col, value=k).font = Font(name="Segoe UI", size=9, color=SLATE, bold=True)
    c = ws.cell(row=5, column=col, value=float(v))
    c.font, c.number_format = Font(name="Segoe UI Semibold", size=14, color=NAVY), f
    ws.cell(row=4, column=col).alignment = Alignment(wrap_text=True)
ws.row_dimensions[4].height = 28

wk = fc.groupby("week").agg(week_start=("date", "min"), forecast=("forecast", "sum"), p10=("p10", "sum"),
                            p90=("p90", "sum"), ly=("ly_sales", "sum"), promo_days=("promo", "max")).reset_index()
wk["vs_ly"] = wk["forecast"] / wk["ly"] - 1
r0 = 8
ws.cell(row=r0 - 1, column=1, value="Chain forecast by week").font = Font(name="Segoe UI Semibold", size=11,
                                                                           color=NAVY)
header(ws, r0, ["Week", "Week starting", "Forecast", "Low (P10)", "High (P90)", "Last year", "vs last year",
                "Promo week"])
for i, r in wk.iterrows():
    row = r0 + 1 + i
    vals = [int(r.week), r.week_start.date(), r.forecast, r.p10, r.p90, r.ly, r.vs_ly, "Yes" if r.promo_days else ""]
    fmts = ["0", "dd mmm yyyy", MONEY, MONEY, MONEY, MONEY, PCT, "@"]
    for j, (v, f) in enumerate(zip(vals, fmts), 1):
        c = ws.cell(row=row, column=j, value=v)
        c.number_format, c.font, c.border = f, BODY, THIN
tot = r0 + 1 + len(wk)
ws.cell(row=tot, column=1, value="Total").font = Font(name="Segoe UI", bold=True)
for j, col in [(3, "C"), (4, "D"), (5, "E"), (6, "F")]:
    c = ws.cell(row=tot, column=j, value=f"=SUM({col}{r0 + 1}:{col}{tot - 1})")
    c.number_format, c.font = MONEY, Font(name="Segoe UI", bold=True)
c = ws.cell(row=tot, column=7, value=f"=C{tot}/F{tot}-1")
c.number_format, c.font = PCT, Font(name="Segoe UI", bold=True)

ch = LineChart()
ch.title, ch.height, ch.width = "Weekly forecast vs last year", 7.5, 17
ch.y_axis.title, ch.y_axis.numFmt = "Sales", '"$"#,##0.0,,"M"'
ch.legend.position = "b"
ch.add_data(Reference(ws, min_col=3, max_col=3, min_row=r0, max_row=tot - 1), titles_from_data=True)
ch.add_data(Reference(ws, min_col=6, max_col=6, min_row=r0, max_row=tot - 1), titles_from_data=True)
ch.add_data(Reference(ws, min_col=4, max_col=5, min_row=r0, max_row=tot - 1), titles_from_data=True)
ch.set_categories(Reference(ws, min_col=1, min_row=r0 + 1, max_row=tot - 1))
ch.x_axis.title = "Week"
ch.x_axis.delete = False
ch.y_axis.delete = False
for s, color, dash in zip(ch.series, ["1F4E79", "B8C2CF", "C8A24A", "C8A24A"], [None, None, "dash", "dash"]):
    s.graphicalProperties.line.solidFill = color
    s.graphicalProperties.line.width = 28000
    s.smooth = False
    if dash:
        s.graphicalProperties.line.dashStyle = dash
ws.add_chart(ch, "J4")
ws.cell(row=tot + 2, column=1, value="How to read this").font = Font(name="Segoe UI Semibold", color=NAVY)
notes = ["Forecast = most likely sales. P10/P90: 8 in 10 outcomes should fall between the low and high case.",
         "Last year = actual sales on the same calendar dates in 2025 (1 Jan - 11 Feb).",
         "Closed days (New Year's Day, Express stores on Sundays) are forecast at $0.",
         "Promo weeks follow the 2026 promotion plan (weeks of 12 Jan, 26 Jan, 9 Feb).",
         "Week 1 is below last year because 2-7 Jan 2025 had four promotion days and the 2026 plan has none.",
         "Backtest: the model forecast three past 6-week windows of 2025 before seeing them; see the Accuracy sheet."]
for i, n in enumerate(notes):
    ws.cell(row=tot + 3 + i, column=1, value="•  " + n).font = Font(name="Segoe UI", size=9, color="334155")
widths(ws, [16, 16, 15, 15, 15, 15, 14, 12])

# ---------------------------------------------------------------- By store
ws = wb.create_sheet("By Store")
title(ws, "Forecast by store and week", "Sales forecast in $; colour scale on the 6-week total, bars on change vs last year")
piv = fc.pivot_table(index=["store_id", "store_name", "format", "region"], columns="week", values="forecast",
                     aggfunc="sum").reset_index()
piv.columns = [c if isinstance(c, str) else f"Week {c}" for c in piv.columns]
tot_s = fc.groupby("store_id").agg(total=("forecast", "sum"), ly=("ly_sales", "sum"))
piv = piv.merge(tot_s, left_on="store_id", right_index=True)
piv["vs_ly"] = piv["total"] / piv["ly"] - 1
cols = ["Store", "Name", "Format", "Region"] + [f"Week {i}" for i in range(1, 7)] + ["6-week total", "Last year",
                                                                                       "vs last year"]
header(ws, 4, cols)
for i, r in enumerate(piv.itertuples(index=False), start=5):
    for j, v in enumerate(r, 1):
        c = ws.cell(row=i, column=j, value=v)
        c.font, c.border = BODY, THIN
        if 5 <= j <= 12:
            c.number_format = MONEY
        if j == 13:
            c.number_format = PCT
last = 4 + len(piv)
ws.conditional_formatting.add(f"K5:K{last}", ColorScaleRule(start_type="min", start_color="EAF0F7",
                                                            end_type="max", end_color="1F4E79"))
ws.conditional_formatting.add(f"M5:M{last}", DataBarRule(start_type="min", end_type="max", color="0E7C86"))
ws.freeze_panes = "E5"
ws.auto_filter.ref = f"A4:M{last}"
widths(ws, [8, 22, 14, 12] + [12] * 6 + [14, 14, 12])

# ---------------------------------------------------------------- Daily detail
ws = wb.create_sheet("Daily Detail")
title(ws, "Daily forecast by store", "Filter by store, date or promo. Use the low/high case for staffing and stock buffers.")
det = fc.sort_values(["store_id", "date"])
det_cols = ["store_id", "store_name", "format", "date", "open", "promo", "holiday_name", "forecast", "p10", "p90",
            "ly_sales"]
names = ["Store", "Name", "Format", "Date", "Open", "Promo", "Holiday", "Forecast", "Low (P10)", "High (P90)",
         "Last year"]
for j, n in enumerate(names, 1):
    ws.cell(row=4, column=j, value=n)
for i, r in enumerate(det[det_cols].itertuples(index=False), start=5):
    for j, v in enumerate(r, 1):
        c = ws.cell(row=i, column=j, value=(v.date() if hasattr(v, "date") else (None if pd.isna(v) else v)))
        if j == 4:
            c.number_format = "ddd dd mmm yyyy"
        elif j >= 8:
            c.number_format = MONEY
last = 4 + len(det)
tab = Table(displayName="DailyForecast", ref=f"A4:K{last}")
tab.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
ws.add_table(tab)
ws.freeze_panes = "A5"
widths(ws, [8, 22, 14, 18, 7, 7, 16, 13, 13, 13, 13])

# ---------------------------------------------------------------- Accuracy
ws = wb.create_sheet("Accuracy")
title(ws, "How accurate is the forecast?",
      "Rolling backtest: each model forecast 3 past 6-week windows of 2025 (origins 31 May, 31 Aug, 19 Nov)")
label = {"naive": "Baseline (same weekday last year)", "prophet": "Prophet (per store)",
         "gbm": "Gradient boosting (global)", "ensemble": "Ensemble (Prophet + GBM)"}
header(ws, 4, ["Model", "WAPE", "MAPE", "RMSE ($/day)", "Bias", "Error vs baseline"])
a = acc[acc.fold == "all"].set_index("model").loc[["naive", "prophet", "gbm", "ensemble"]]
for i, (mname, r) in enumerate(a.iterrows(), start=5):
    vals = [label[mname] + ("  ← used" if mname == model else ""), r.WAPE, r.MAPE, r.RMSE, r.Bias,
            r.WAPE / a.loc["naive", "WAPE"] - 1]
    for j, (v, f) in enumerate(zip(vals, ["@", "0.0%", "0.0%", '"$"#,##0', PCT, PCT]), 1):
        c = ws.cell(row=i, column=j, value=v)
        c.number_format, c.font, c.border = f, Font(name="Segoe UI", size=10, bold=mname == model), THIN
ws.cell(row=10, column=1, value="WAPE = total absolute error ÷ total sales. Bias > 0 means over-forecasting."
        ).font = Font(name="Segoe UI", size=9, color=SLATE)
header(ws, 12, ["Store", "Name", "Format", "Baseline WAPE", "Prophet WAPE", "GBM WAPE", "Ensemble WAPE"])
s = acc_store.merge(stores[["store_id", "store_name", "format"]], on="store_id")
for i, r in enumerate(s.itertuples(index=False), start=13):
    vals = [r.store_id, r.store_name, r.format, r.naive_wape, r.prophet_wape, r.gbm_wape, r.ensemble_wape]
    for j, v in enumerate(vals, 1):
        c = ws.cell(row=i, column=j, value=v)
        c.font, c.border = BODY, THIN
        if j >= 4:
            c.number_format = "0.0%"
last = 12 + len(s)
ws.conditional_formatting.add(f"D13:G{last}", ColorScaleRule(start_type="num", start_value=0.03,
                                                             start_color="D3ECEE", mid_type="num", mid_value=0.07,
                                                             mid_color="FFFFFF", end_type="num", end_value=0.12,
                                                             end_color="F3D7CF"))
bc = BarChart()
bc.type, bc.title, bc.height, bc.width = "bar", "WAPE by model (lower is better)", 6.5, 13
bc.add_data(Reference(ws, min_col=2, min_row=4, max_row=8), titles_from_data=True)
bc.set_categories(Reference(ws, min_col=1, min_row=5, max_row=8))
bc.y_axis.numFmt, bc.legend = "0%", None
bc.x_axis.delete = False
bc.y_axis.delete = False
bc.series[0].graphicalProperties.solidFill = "1F4E79"
ws.add_chart(bc, "I4")
widths(ws, [34, 22, 14, 14, 14, 14, 16])

# ---------------------------------------------------------------- Drivers
ws = wb.create_sheet("Sales Drivers")
title(ws, "What moves daily sales?",
      "Fixed-effects regression on 62,555 store-days. Synthetic data: 'true' is the value the simulator used.")
header(ws, 4, ["Group", "Effect", "Estimated", "95% CI low", "95% CI high", "True (simulated)"])
for i, r in enumerate(drivers.itertuples(index=False), start=5):
    vals = [r.group, r.effect, r.estimated, r.ci_low, r.ci_high, r.true]
    for j, v in enumerate(vals, 1):
        c = ws.cell(row=i, column=j, value=None if (isinstance(v, float) and pd.isna(v)) else v)
        c.font, c.border = BODY, THIN
        if j >= 3:
            c.number_format = "+0.0%;-0.0%"
widths(ws, [14, 46, 12, 12, 12, 16])

# ---------------------------------------------------------------- Method
ws = wb.create_sheet("Method")
title(ws, "Method and data", "")
lines = [
    "Data: synthetic daily sales for 60 stores, Jan 2023 – Dec 2025, generated by scripts/generate_data.py.",
    "Cleaning: date formats standardised, duplicates removed, sign typos fixed, POS outages excluded (scripts/clean.py).",
    "Models: same-weekday-last-year baseline; Prophet per store with promo, holiday, school, payday, loyalty,",
    "        competitor and refurbishment regressors; one global gradient-boosting model with calendar, store and",
    "        lagged-level features (all lags 42+ days, so nothing from the forecast window is used).",
    "Validation: rolling-origin backtest over three 42-day windows of 2025; open days only.",
    f"Selected model: {model_label} (lowest backtest WAPE). Low/high case from quantile gradient boosting.",
    "Code: github.com/talha-ather-pk/retail-demand-forecasting",
]
for i, l in enumerate(lines, start=3):
    ws.cell(row=i, column=1, value=l).font = Font(name="Segoe UI", size=10)
ws.column_dimensions["A"].width = 120

path = OUT / "Corvane_6-week_forecast_2026.xlsx"
wb.save(path)
print(f"wrote {path.relative_to(ROOT)}  ({len(wb.sheetnames)} sheets: {', '.join(wb.sheetnames)})")
