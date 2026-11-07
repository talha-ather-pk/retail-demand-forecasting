"""
Corvane Drugstores: generate the forecasting dashboard as a Power BI Project (PBIP).

Writes powerbi/Corvane.pbip:
  Corvane.SemanticModel/  history, forecast and backtest facts sharing store and date dimensions,
                          driver estimates, measures table (TMDL)
  Corvane.Report/         custom theme, sidebar navigation, 3 report pages, a Store Detail
                          drill-through page and a day tooltip page (PBIR JSON)

Open the .pbip in Power BI Desktop (Nov 2025 release or later) and click Refresh.
Run: python scripts/build_pbip.py   (from the project root)
"""
import json
import shutil
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PBI = ROOT / "powerbi"
NAME = "Corvane"
SM = PBI / f"{NAME}.SemanticModel"
RP = PBI / f"{NAME}.Report"
DATA_FOLDER = str(ROOT / "data_clean") + "\\"
BASE_THEME = "CY26SU04"
THEME_SRC = Path(r"C:\Program Files\Microsoft Power BI Desktop\bin\WebView2Resources"
                 r"\minerva\sharedresources\BaseThemes") / f"{BASE_THEME}.json"
CUSTOM_THEME = "Corvane_Executive.json"
SCHEMA = "https://developer.microsoft.com/json-schemas/fabric"
V_VISUAL, V_PAGE, V_REPORT = "2.4.0", "2.0.0", "3.0.0"

# =========================================================================
# Design system
# =========================================================================
NAVY = "#0B1F3A"        # sidebar, primary text on light
NAVY_2 = "#16314F"      # active nav item
INK = "#0F172A"
SLATE = "#64748B"
SLATE_2 = "#94A3B8"
MIST = "#CBD5E1"
LINE = "#E6E9F0"
CANVAS = "#F3F5F9"
WHITE = "#FFFFFF"
GOLD = "#C8A24A"
PRIMARY = "#1F4E79"     # main series
COMPARE = "#B8C2CF"     # prior year / comparison series
GOOD, WARN, BAD, NEUTRAL = "#0E7C86", "#D08C2E", "#B5523B", "#94A3B8"
DATA_COLORS = [PRIMARY, GOOD, GOLD, "#7A8CA5", BAD, "#5B8E7D", "#8C6BB1", WARN]
FONT, FONT_SB, FONT_LIGHT = "Segoe UI", "Segoe UI Semibold", "Segoe UI Light"


def gid(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "corvane/" + "/".join(parts)))


def hid(*parts):
    return gid(*parts).replace("-", "")[:20]


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path, obj):
    write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


# =========================================================================
# Semantic model
# =========================================================================
S, I, D, DT, B = "string", "int64", "double", "dateTime", "boolean"
MTYPE = {S: "type text", I: "Int64.Type", D: "type number", DT: "type date", B: "logical"}


def cols(*spec):
    """(name, type[, hidden[, extra]]) -> column tuples. Every column summarizeBy none."""
    out = []
    for name, dtype, *rest in spec:
        hidden = bool(rest and rest[0])
        extra = dict(rest[1]) if len(rest) > 1 else {}
        if dtype == DT:
            extra.setdefault("formatString", "dd mmm yyyy")
        out.append((name, dtype, hidden, extra))
    return out


# table -> (csv file or None, columns loaded, extra M steps (list of (name, expr using {prev})), derived columns)
TABLES = {
    "fact_sales": ("daily.csv", cols(
        ("store_id", I, True), ("date", DT, True), ("open", I, True), ("promo", I, True),
        ("state_holiday", I, True), ("holiday_name", S, True), ("school_holiday", I, True),
        ("sales", D, True), ("customers", D, True), ("is_outage", I, True), ("usable", I, True),
        ("is_future", I, True)),
        [("Hist", 'Table.SelectRows({prev}, each [is_future] = 0)')], []),
    "fact_forecast": ("forecast_2026.csv", cols(
        ("store_id", I, True), ("date", DT, True), ("open", I, True), ("promo", I, True),
        ("state_holiday", I, True), ("holiday_name", S, True), ("school_holiday", I, True),
        ("forecast_prophet", D, True), ("forecast_gbm", D, True), ("forecast_ensemble", D, True),
        ("forecast", D, True), ("p10", D, True), ("p90", D, True), ("model", S, True)), [], []),
    "fact_backtest": ("backtest_predictions.csv", cols(
        ("store_id", I, True), ("date", DT, True), ("open", I, True), ("usable", I, True),
        ("sales", D, True), ("fold", I), ("naive", D, True), ("prophet", D, True), ("gbm", D, True),
        ("ensemble", D, True)),
        [("Long", 'Table.Unpivot({prev}, {{"naive", "prophet", "gbm", "ensemble"}}, "model", "prediction")'),
         ("Label", 'Table.AddColumn({prev}, "model_label", each if [model] = "naive" then "Baseline" else '
                   'if [model] = "prophet" then "Prophet" else if [model] = "gbm" then "Gradient boosting" '
                   'else "Ensemble", type text)'),
         ("Order", 'Table.AddColumn({prev}, "model_order", each if [model] = "naive" then 1 else '
                   'if [model] = "prophet" then 2 else if [model] = "gbm" then 3 else 4, Int64.Type)'),
         ("Window", 'Table.AddColumn({prev}, "backtest_window", each if [fold] = 1 then "1 · Jun-Jul 2025" '
                    'else if [fold] = 2 then "2 · Sep-Oct 2025" else "3 · Nov-Dec 2025", type text)')],
        cols(("model", S, True), ("prediction", D, True), ("model_label", S, False, {"sortByColumn": "model_order"}),
             ("model_order", I, True), ("backtest_window", S))),
    "dim_store": ("stores.csv", cols(
        ("store_id", I, True), ("store_name", S), ("format", S), ("region", S), ("assortment", S),
        ("sq_ft", I, True), ("competition_distance_m", D, True), ("opened_year", I, True), ("promo2", I, True),
        ("competitor_opened", DT, True), ("new_competitor_distance_m", D, True)),
        [("Loyalty", 'Table.AddColumn({prev}, "loyalty_programme", each if [promo2] = 1 then "Yes" else "No", type text)'),
         ("Comp", 'Table.AddColumn({prev}, "new_competitor", each if [competitor_opened] = null then "No" else "Yes", type text)')],
        cols(("loyalty_programme", S), ("new_competitor", S))),
    "dim_date": (None, cols(("date", DT, False, {"isKey": None})), [], cols(
        ("year", I), ("month_num", I, True), ("month", S, False, {"sortByColumn": "month_num"}),
        ("month_start", DT, False, {"formatString": "mmm yyyy"}), ("week_start", DT, False, {"formatString": "dd mmm yyyy"}),
        ("weekday_num", I, True), ("weekday", S, False, {"sortByColumn": "weekday_num"}))),
    "driver_effects": ("driver_effects.csv", cols(
        ("group", S), ("effect", S), ("estimated", D, True), ("ci_low", D, True), ("ci_high", D, True),
        ("true", D, True)), [], []),
    "competitor_effects": ("competitor_effects.csv", cols(
        ("store_id", I, True), ("new_competitor_distance_m", D, True), ("estimated_hit", D, True),
        ("true_hit", D, True)), [], []),
}

DIM_DATE_M = [
    "let",
    "    Dates = List.Dates(#date(2023, 1, 1), Duration.Days(#date(2026, 2, 11) - #date(2023, 1, 1)) + 1, "
    "#duration(1, 0, 0, 0)),",
    '    Base = Table.FromList(Dates, Splitter.SplitByNothing(), type table [date = date]),',
    '    Year = Table.AddColumn(Base, "year", each Date.Year([date]), Int64.Type),',
    '    MonthNum = Table.AddColumn(Year, "month_num", each Date.Month([date]), Int64.Type),',
    '    Month = Table.AddColumn(MonthNum, "month", each Date.ToText([date], "MMM", "en-US"), type text),',
    '    MonthStart = Table.AddColumn(Month, "month_start", each Date.StartOfMonth([date]), type date),',
    '    WeekStart = Table.AddColumn(MonthStart, "week_start", each Date.StartOfWeek([date], Day.Monday), type date),',
    '    WeekdayNum = Table.AddColumn(WeekStart, "weekday_num", each Date.DayOfWeek([date], Day.Monday) + 1, Int64.Type),',
    '    Weekday = Table.AddColumn(WeekdayNum, "weekday", each Date.ToText([date], "ddd", "en-US"), type text)',
    "in",
    "    Weekday",
]

RELATIONSHIPS = [
    ("fact_sales", "date", "dim_date", "date"), ("fact_sales", "store_id", "dim_store", "store_id"),
    ("fact_forecast", "date", "dim_date", "date"), ("fact_forecast", "store_id", "dim_store", "store_id"),
    ("fact_backtest", "date", "dim_date", "date"), ("fact_backtest", "store_id", "dim_store", "store_id"),
    ("competitor_effects", "store_id", "dim_store", "store_id"),
]

# ---------------------------------------------------------------- measures
CUR, CUR2, PCT, INT, DEC1, DEC2 = (r"\$#,0;(\$#,0);\$#,0", r"\$#,0.00;(\$#,0.00);\$#,0.00",
                                   "0.0%;-0.0%;0.0%", "#,0", "#,0.0", "#,0.00")
SPCT = "+0.0%;-0.0%;0.0%"
MEASURES = []   # (name, dax, format, folder, hidden)


def m(name, dax, fmt=None, folder="", hidden=False):
    MEASURES.append((name, dax, fmt, folder, hidden))


USABLE = "fact_sales[usable] = 1"
BT_USABLE = "fact_backtest[usable] = 1"
# History -------------------------------------------------------------------------
m("Actual Sales", "SUM ( fact_sales[sales] )", CUR, "1 History")
m("Open Store Days", f"CALCULATE ( COUNTROWS ( fact_sales ), {USABLE} )", INT, "1 History")
m("Avg Sales per Open Day", "DIVIDE ( CALCULATE ( [Actual Sales], fact_sales[usable] = 1 ), [Open Store Days] )",
  CUR, "1 History")
m("Customers", "SUM ( fact_sales[customers] )", INT, "1 History")
m("Avg Basket", "DIVIDE ( [Actual Sales], [Customers] )", CUR2, "1 History")
m("Actual Sales (Recent)", 'IF ( MAX ( dim_date[date] ) >= DATE ( 2025, 10, 1 ), [Actual Sales] )', CUR, "1 History")
m("Actual Sales 2025", "CALCULATE ( [Actual Sales], dim_date[year] = 2025 )", CUR, "1 History")
m("Actual Sales 2024", "CALCULATE ( [Actual Sales], dim_date[year] = 2024 )", CUR, "1 History")
m("Sales Growth 2025", "DIVIDE ( [Actual Sales 2025] - [Actual Sales 2024], [Actual Sales 2024] )", SPCT, "1 History")
# Forecast --------------------------------------------------------------------------
m("Forecast", "SUM ( fact_forecast[forecast] )", CUR, "2 Forecast")
m("Forecast P10", "SUM ( fact_forecast[p10] )", CUR, "2 Forecast")
m("Forecast P90", "SUM ( fact_forecast[p90] )", CUR, "2 Forecast")
m("Forecast Prophet", "SUM ( fact_forecast[forecast_prophet] )", CUR, "2 Forecast")
m("Forecast Gradient Boosting", "SUM ( fact_forecast[forecast_gbm] )", CUR, "2 Forecast")
# same calendar dates one year earlier: 7-day blocks keep the same weekdays and New Year's Day lines up
m("Sales Same Dates LY",
  "CALCULATE ( [Actual Sales], REMOVEFILTERS ( dim_date ), "
  "TREATAS ( SELECTCOLUMNS ( VALUES ( fact_forecast[date] ), \"d\", fact_forecast[date] - 365 ), dim_date[date] ) )",
  CUR, "2 Forecast")
m("Forecast vs LY %", "DIVIDE ( [Forecast] - [Sales Same Dates LY], [Sales Same Dates LY] )", SPCT, "2 Forecast")
m("Forecast Range Label",
  'FORMAT ( [Forecast P10] / 1000000, "$0.00" ) & "M  –  " & FORMAT ( [Forecast P90] / 1000000, "$0.00" ) & "M"',
  None, "2 Forecast")
m("Forecast vs LY Label",
  'IF ( ISBLANK ( [Sales Same Dates LY] ), "", FORMAT ( [Forecast vs LY %], "▲ 0.0%;▼ 0.0%;● 0.0%" ) & "  vs same dates 2025" )',
  None, "2 Forecast")
m("Forecast Days", "COUNTROWS ( VALUES ( fact_forecast[date] ) )", INT, "2 Forecast", hidden=True)
m("Selected Model", 'SELECTEDVALUE ( fact_forecast[model], "ensemble" )', None, "2 Forecast", hidden=True)
m("Selected Model Label",
  'SWITCH ( [Selected Model], "gbm", "Gradient boosting", "prophet", "Prophet", "ensemble", "Ensemble (Prophet + GBM)", "Baseline" )',
  None, "2 Forecast")
# Accuracy --------------------------------------------------------------------------
m("Backtest Actual",
  f'CALCULATE ( SUM ( fact_backtest[sales] ), {BT_USABLE}, REMOVEFILTERS ( fact_backtest[model], '
  f'fact_backtest[model_label], fact_backtest[model_order] ), fact_backtest[model] = "naive" )', CUR, "3 Accuracy")
m("Backtest Forecast", f"CALCULATE ( SUM ( fact_backtest[prediction] ), {BT_USABLE} )", CUR, "3 Accuracy")
m("Abs Error",
  f"SUMX ( FILTER ( fact_backtest, {BT_USABLE} ), ABS ( fact_backtest[prediction] - fact_backtest[sales] ) )",
  CUR, "3 Accuracy", hidden=True)
m("Signed Error", f"SUMX ( FILTER ( fact_backtest, {BT_USABLE} ), fact_backtest[prediction] - fact_backtest[sales] )",
  CUR, "3 Accuracy", hidden=True)
m("Backtest Sales (per model)", f"CALCULATE ( SUM ( fact_backtest[sales] ), {BT_USABLE} )", CUR, "3 Accuracy", hidden=True)
m("WAPE", "DIVIDE ( [Abs Error], [Backtest Sales (per model)] )", PCT, "3 Accuracy")
m("Bias %", "DIVIDE ( [Signed Error], [Backtest Sales (per model)] )", SPCT, "3 Accuracy")
m("MAPE",
  f"AVERAGEX ( FILTER ( fact_backtest, {BT_USABLE} ), DIVIDE ( ABS ( fact_backtest[prediction] - fact_backtest[sales] ), fact_backtest[sales] ) )",
  PCT, "3 Accuracy")
m("WAPE Selected Model", "VAR mdl = [Selected Model] RETURN CALCULATE ( [WAPE], fact_backtest[model] = mdl )",
  PCT, "3 Accuracy")
m("WAPE Baseline", 'CALCULATE ( [WAPE], fact_backtest[model] = "naive" )', PCT, "3 Accuracy")
m("Error Reduction vs Baseline", "1 - DIVIDE ( [WAPE Selected Model], [WAPE Baseline] )", PCT, "3 Accuracy")
m("Bias Selected Model", "VAR mdl = [Selected Model] RETURN CALCULATE ( [Bias %], fact_backtest[model] = mdl )",
  SPCT, "3 Accuracy")
m("MAPE Selected Model", "VAR mdl = [Selected Model] RETURN CALCULATE ( [MAPE], fact_backtest[model] = mdl )",
  PCT, "3 Accuracy")
m("Forecast Selected Model (Backtest)",
  "VAR mdl = [Selected Model] RETURN CALCULATE ( [Backtest Forecast], fact_backtest[model] = mdl )", CUR, "3 Accuracy")
m("Forecast Baseline (Backtest)", 'CALCULATE ( [Backtest Forecast], fact_backtest[model] = "naive" )', CUR, "3 Accuracy")
m("Error Reduction Label",
  'FORMAT ( [Error Reduction vs Baseline], "0%" ) & " lower error than baseline"', None, "3 Accuracy")
m("Baseline Label", '"Same weekday last year"', None, "9 Helpers", hidden=True)
m("Bias Label", 'IF ( [Bias Selected Model] >= 0, "Slight over-forecast", "Slight under-forecast" )', None,
  "9 Helpers", hidden=True)
m("MAPE Label", '"Average daily % error"', None, "9 Helpers", hidden=True)
# Drivers ---------------------------------------------------------------------------
m("Estimated Effect", "SUM ( driver_effects[estimated] )", SPCT, "4 Drivers")
m("True Effect (Simulated)", "SUM ( driver_effects[true] )", SPCT, "4 Drivers")
m("Effect CI Low", "SUM ( driver_effects[ci_low] )", SPCT, "4 Drivers")
m("Effect CI High", "SUM ( driver_effects[ci_high] )", SPCT, "4 Drivers")
m("Promo Lift Neighborhood", 'CALCULATE ( [Estimated Effect], driver_effects[effect] = "Promotion lift, Neighborhood (basic assortment)" )',
  SPCT, "4 Drivers")
m("Promo Lift Flagship", 'CALCULATE ( [Estimated Effect], driver_effects[effect] = "Promotion lift, Flagship (basic assortment)" )',
  SPCT, "4 Drivers")
m("Promo Lift Express", 'CALCULATE ( [Estimated Effect], driver_effects[effect] = "Promotion lift, Express (basic assortment)" )',
  SPCT, "4 Drivers")
m("Payday Lift", 'CALCULATE ( [Estimated Effect], driver_effects[effect] = "Payday (1st-3rd, 15th-16th)" )', SPCT, "4 Drivers")
m("Competitor Distance", "AVERAGE ( competitor_effects[new_competitor_distance_m] )", "#,0", "4 Drivers")
m("Competitor Hit", "AVERAGE ( competitor_effects[estimated_hit] )", PCT, "4 Drivers")
m("Competitor Hit (True)", "AVERAGE ( competitor_effects[true_hit] )", PCT, "4 Drivers")
m("Note True", 'FORMAT ( [True Effect (Simulated)], "+0%;-0%" ) & " built into the simulation"', None, "9 Helpers", hidden=True)
m("Note Promo Neighborhood", 'FORMAT ( CALCULATE ( [True Effect (Simulated)], driver_effects[effect] = "Promotion lift, Neighborhood (basic assortment)" ), "+0%" ) & " simulated"', None, "9 Helpers", hidden=True)
m("Note Promo Flagship", 'FORMAT ( CALCULATE ( [True Effect (Simulated)], driver_effects[effect] = "Promotion lift, Flagship (basic assortment)" ), "+0%" ) & " simulated"', None, "9 Helpers", hidden=True)
m("Note Promo Express", 'FORMAT ( CALCULATE ( [True Effect (Simulated)], driver_effects[effect] = "Promotion lift, Express (basic assortment)" ), "+0%" ) & " simulated"', None, "9 Helpers", hidden=True)
m("Note Payday", 'FORMAT ( CALCULATE ( [True Effect (Simulated)], driver_effects[effect] = "Payday (1st-3rd, 15th-16th)" ), "+0%" ) & " simulated"', None, "9 Helpers", hidden=True)
m("Note Competitor", 'FORMAT ( [Competitor Hit (True)], "0%" ) & " simulated, 12 stores"', None, "9 Helpers", hidden=True)
# Store ------------------------------------------------------------------------------
m("Store WAPE", "[WAPE Selected Model]", PCT, "5 Stores")
m("Stores", "DISTINCTCOUNT ( dim_store[store_id] )", INT, "5 Stores")
m("Store Forecast Rank", "IF ( ISINSCOPE ( dim_store[store_name] ), RANKX ( ALLSELECTED ( dim_store[store_name] ), [Forecast], , DESC, DENSE ) )",
  "#,0", "5 Stores")
# Dynamic text -----------------------------------------------------------------------


def _sel(colref, all_text):
    return (f'IF ( ISFILTERED ( {colref} ), CONCATENATEX ( VALUES ( {colref} ), {colref}, ", ", {colref}, ASC ), '
            f'"{all_text}" )')


m("Filter Context",
  f'{_sel("dim_store[region]", "All regions")} & "   ·   " & {_sel("dim_store[format]", "All formats")} & '
  f'"   ·   " & {_sel("dim_store[store_name]", "All 60 stores")} & "   ·   forecast 1 Jan – 11 Feb 2026"',
  None, "7 Dynamic text")
m("Blank Text", '""', None, "9 Helpers", hidden=True)
m("Note P10", '"8 in 10 outcomes above this"', None, "9 Helpers", hidden=True)
m("Note P90", '"8 in 10 outcomes below this"', None, "9 Helpers", hidden=True)
m("Note LY", '"Actual, 1 Jan – 11 Feb 2025"', None, "9 Helpers", hidden=True)
m("Note History", '"Open days, 2023 – 2025"', None, "9 Helpers", hidden=True)
m("Title Tooltip", 'FORMAT ( MAX ( dim_date[date] ), "dddd d mmm yyyy" )', None, "7 Dynamic text")
m("Title Forecast Trend", '"Daily sales: actual Oct–Dec 2025 and forecast to 11 Feb 2026  ·  " & [Selected Model Label]',
  None, "7 Dynamic text")
m("Title Store", 'SELECTEDVALUE ( dim_store[store_name], "Multiple stores" ) & "  ·  " & '
  'SELECTEDVALUE ( dim_store[format], "" ) & " store detail"', None, "7 Dynamic text")
m("Title Accuracy Trend", '"Backtests: actual vs " & [Selected Model Label] & " vs baseline (three 6-week windows)"',
  None, "7 Dynamic text")
# Formatting -------------------------------------------------------------------------
m("vs LY Color", f'IF ( [Forecast vs LY %] >= 0, "{GOOD}", "{BAD}" )', None, "8 Formatting", hidden=True)
m("WAPE Heat", 'VAR w = [WAPE] RETURN SWITCH ( TRUE (), ISBLANK ( w ), BLANK (), w < 0.05, "#D3ECEE", '
  'w < 0.07, "#EEF6F6", w < 0.09, "#F7E6CC", "#F3D7CF" )', None, "8 Formatting", hidden=True)
m("Model Color", f'IF ( SELECTEDVALUE ( fact_backtest[model] ) = [Selected Model], "{PRIMARY}", '
  f'IF ( SELECTEDVALUE ( fact_backtest[model] ) = "naive", "{COMPARE}", "#7FA3C7" ) )', None, "8 Formatting", hidden=True)
m("Effect Color", f'IF ( [Estimated Effect] >= 0, "{GOOD}", "{BAD}" )', None, "8 Formatting", hidden=True)
m("Neutral Color", f'"{SLATE}"', None, "8 Formatting", hidden=True)


def q(name):
    return name if name.replace("_", "").isalnum() else f"'{name}'"


def col_tmdl(table, name, dtype, hidden, extra):
    out = [f"\tcolumn {q(name)}", f"\t\tdataType: {dtype}"]
    if hidden:
        out.append("\t\tisHidden")
    for k, v in extra.items():
        out.append(f"\t\t{k}" if v is None else f"\t\t{k}: {v}")
    if dtype == I and "formatString" not in extra:
        out.append("\t\tformatString: 0")
    out += [f"\t\tlineageTag: {gid(table, name)}", "\t\tsummarizeBy: none", f"\t\tsourceColumn: {name}",
            "", "\t\tannotation SummarizationSetBy = User", ""]
    return out


def m_partition(table):
    csv, columns, steps_extra, _ = TABLES[table]
    if csv is None:
        return DIM_DATE_M
    types = ", ".join(f'{{"{n}", {MTYPE[t]}}}' for n, t, _, _ in columns if t != B)
    steps = [
        ("Source", f'Csv.Document(File.Contents(DataFolder & "{csv}"), [Delimiter = ",", Encoding = 65001, '
                   'QuoteStyle = QuoteStyle.Csv])'),
        ("Promoted", "Table.PromoteHeaders(Source, [PromoteAllScalars = true])"),
        ("Kept", "Table.SelectColumns(Promoted, {" + ", ".join(f'"{n}"' for n, *_ in columns) + "})"),
        ("Blanks", 'Table.TransformColumns(Kept, {}, each if _ = "" then null else _)'),
        ("Typed", f'Table.TransformColumnTypes(Blanks, {{{types}}}, "en-US")'),
    ]
    prev = "Typed"
    for name, expr in steps_extra:
        steps.append((name, expr.format(prev=prev)))
        prev = name
    lines = [f"    {n} = {e}," for n, e in steps]
    lines[-1] = lines[-1].rstrip(",")
    return ["let"] + lines + ["in", f"    {prev}"]


UNPIVOTED = {"naive", "prophet", "gbm", "ensemble"}


def tmdl_table(table):
    _, columns, _, derived = TABLES[table]
    out = [f"table {table}", f"\tlineageTag: {gid(table)}", ""]
    if table == "dim_date":
        out.insert(1, "\tdataCategory: Time")
    for c in columns + derived:
        if table == "fact_backtest" and c[0] in UNPIVOTED:     # turned into rows (model, prediction)
            continue
        out += col_tmdl(table, *c)
    out += [f"\tpartition {table} = m", "\t\tmode: import", "\t\tsource ="]
    out += ["\t\t\t\t" + line for line in m_partition(table)]
    out += ["", "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(out)


def tmdl_measures():
    out = ["table _Measures", f"\tlineageTag: {gid('_Measures')}", ""]
    for name, dax, fmt, folder, hidden in MEASURES:
        out.append(f"\tmeasure {q(name)} = {dax}")
        if fmt:
            out.append(f"\t\tformatString: {fmt}")
        if hidden:
            out.append("\t\tisHidden")
        out += [f"\t\tdisplayFolder: {folder}", f"\t\tlineageTag: {gid('m', name)}", ""]
    out += ["\tcolumn Value", "\t\tdataType: string", "\t\tisHidden", f"\t\tlineageTag: {gid('_Measures', 'Value')}",
            "\t\tsummarizeBy: none", "\t\tsourceColumn: Value", "",
            "\t\tannotation SummarizationSetBy = Automatic", "",
            "\tpartition _Measures = m", "\t\tmode: import", "\t\tsource =",
            '\t\t\t\t#table(type table [Value = text], {})', "",
            "\tannotation PBI_ResultType = Table", ""]
    return "\n".join(out)


def build_semantic_model():
    if SM.exists():
        shutil.rmtree(SM)
    write_json(SM / "definition.pbism", {
        "$schema": f"{SCHEMA}/item/semanticModel/definitionProperties/1.0.0/schema.json",
        "version": "4.2", "settings": {}})
    write_json(SM / ".platform", {
        "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "SemanticModel", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": gid("sm")}})
    d = SM / "definition"
    write(d / "database.tmdl", "database\n\tcompatibilityLevel: 1600\n\n")
    tables = ["_Measures", *TABLES]
    write(d / "model.tmdl", "\n".join([
        "model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tdiscourageImplicitMeasures", "\tsourceQueryCulture: en-US", "\tdataAccessOptions",
        "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
        f"annotation PBI_QueryOrder = {json.dumps(['DataFolder', *tables])}", "",
        "annotation __PBI_TimeIntelligenceEnabled = 0", "",
        *[f"ref table {t}" for t in tables], ""]))
    write(d / "expressions.tmdl", "\n".join([
        f'expression DataFolder = "{DATA_FOLDER}" meta [IsParameterQuery = true, Type = "Text", '
        "IsParameterQueryRequired = true]",
        f"\tlineageTag: {gid('DataFolder')}", "", "\tannotation PBI_ResultType = Text", ""]))
    rels = []
    for ft, fc, tt, tc in RELATIONSHIPS:
        rels += [f"relationship {gid('rel', ft, fc, tt)}"]
        if tc == "date":
            rels += ["\tjoinOnDateBehavior: datePartOnly"]
        rels += [f"\tfromColumn: {ft}.{fc}", f"\ttoColumn: {tt}.{tc}", ""]
    write(d / "relationships.tmdl", "\n".join(rels))
    write(d / "tables" / "_Measures.tmdl", tmdl_measures())
    for t in TABLES:
        write(d / "tables" / f"{t}.tmdl", tmdl_table(t))


# =========================================================================
# Theme
# =========================================================================
def sc(c):
    return {"solid": {"color": c}}


THEME = {
    "name": "Corvane Executive",
    "dataColors": DATA_COLORS,
    "foreground": INK, "foregroundNeutralSecondary": SLATE, "foregroundNeutralTertiary": SLATE_2,
    "background": WHITE, "backgroundLight": "#F6F8FB", "backgroundNeutral": LINE,
    "tableAccent": PRIMARY, "good": GOOD, "neutral": WARN, "bad": BAD,
    "maximum": PRIMARY, "center": "#7FA3C7", "minimum": "#EAF0F7", "null": "#F1F3F7",
    "hyperlink": PRIMARY, "visitedHyperlink": PRIMARY,
    "textClasses": {
        "callout": {"fontSize": 24, "fontFace": FONT_SB, "color": INK},
        "title": {"fontSize": 11, "fontFace": FONT_SB, "color": INK},
        "header": {"fontSize": 10, "fontFace": FONT_SB, "color": "#334155"},
        "label": {"fontSize": 9, "fontFace": FONT, "color": "#475569"},
    },
    "visualStyles": {
        "*": {"*": {
            "background": [{"show": True, "color": sc(WHITE), "transparency": 0}],
            "border": [{"show": True, "color": sc(LINE), "radius": 12, "width": 1}],
            "dropShadow": [{"show": True, "color": sc(NAVY), "position": "Outer", "preset": "Custom",
                            "transparency": 90, "shadowBlur": 14, "shadowDistance": 3, "shadowSpread": 0,
                            "angle": 90}],
            "padding": [{"top": 12, "bottom": 10, "left": 14, "right": 14}],
            "title": [{"show": True, "fontColor": sc(INK), "fontSize": 11, "fontFamily": FONT_SB,
                       "titleWrap": True}],
            "subTitle": [{"fontColor": sc(SLATE), "fontSize": 9, "fontFamily": FONT}],
            "categoryAxis": [{"showAxisTitle": False, "gridlineStyle": "dotted", "labelColor": sc(SLATE),
                              "fontSize": 9, "concatenateLabels": False}],
            "valueAxis": [{"showAxisTitle": False, "gridlineStyle": "dotted", "gridlineColor": sc(LINE),
                           "labelColor": sc(SLATE), "fontSize": 9}],
            "legend": [{"show": True, "position": "TopLeft", "labelColor": sc("#475569"), "fontSize": 9,
                        "showTitle": False}],
            "labels": [{"color": sc("#334155"), "fontSize": 9}],
            "lineStyles": [{"strokeWidth": 3}],
            "outspacePane": [{"backgroundColor": sc(WHITE), "foregroundColor": sc(INK), "transparency": 0,
                              "border": True, "borderColor": sc(LINE)}],
        }},
        "page": {"*": {"background": [{"color": sc(CANVAS), "transparency": 0}],
                       "outspace": [{"color": sc("#E7EBF1"), "transparency": 0}]}},
        "card": {"*": {"labels": [{"color": sc(INK), "fontSize": 24, "fontFamily": FONT_SB}],
                       "categoryLabels": [{"show": False}],
                       "title": [{"alignment": "center", "fontSize": 9, "fontColor": sc(SLATE),
                                  "fontFamily": FONT_SB}]}},
        "tableEx": {"*": {
            "grid": [{"gridVertical": False, "gridHorizontal": True, "gridHorizontalColor": sc("#EEF1F6"),
                      "outlineColor": sc(LINE), "rowPadding": 5}],
            "columnHeaders": [{"fontColor": sc("#475569"), "backColor": sc("#F6F8FB"), "fontFamily": FONT_SB,
                               "fontSize": 9, "wordWrap": True}],
            "values": [{"fontColorPrimary": sc("#1E293B"), "backColorPrimary": sc(WHITE),
                        "fontColorSecondary": sc("#1E293B"), "backColorSecondary": sc("#FAFBFD"), "fontSize": 9}],
            "total": [{"fontFamily": FONT_SB, "backColor": sc("#F6F8FB"), "fontColor": sc(INK)}]}},
        "pivotTable": {"*": {
            "grid": [{"gridVertical": False, "gridHorizontal": True, "gridHorizontalColor": sc("#EEF1F6"),
                      "outlineColor": sc(LINE), "rowPadding": 5}],
            "columnHeaders": [{"fontColor": sc("#475569"), "backColor": sc("#F6F8FB"), "fontFamily": FONT_SB,
                               "fontSize": 9}],
            "rowHeaders": [{"fontColor": sc("#1E293B"), "fontSize": 9, "showExpandCollapseButtons": False,
                            "legacyStyleDisabled": True}],
            "values": [{"fontColorPrimary": sc("#1E293B"), "backColorPrimary": sc(WHITE),
                        "backColorSecondary": sc(WHITE), "fontSize": 9}],
            "subTotals": [{"fontFamily": FONT_SB, "backgroundColor": sc("#F6F8FB")}]}},
        "slicer": {"*": {
            "header": [{"show": True, "fontColor": sc(MIST), "textSize": 8, "fontFamily": FONT_SB,
                        "outline": "None"}],
            "items": [{"fontColor": sc(INK), "background": sc(WHITE), "textSize": 9, "outline": "None"}],
            "background": [{"show": False}], "border": [{"show": False}], "dropShadow": [{"show": False}],
            "padding": [{"top": 0, "bottom": 0, "left": 0, "right": 0}]}},
        "textbox": {"*": {"background": [{"show": False}], "border": [{"show": False}],
                          "dropShadow": [{"show": False}], "padding": [{"top": 0, "bottom": 0, "left": 0,
                                                                         "right": 0}]}},
        "actionButton": {"*": {"background": [{"show": False}], "border": [{"show": False}],
                               "dropShadow": [{"show": False}], "visualHeader": [{"show": False}]}},
    },
}


# =========================================================================
# Report helpers (PBIR)
# =========================================================================
def lit(v):
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, (int, float)):
        s = f"{v}D"
    else:
        s = "'" + str(v).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": s}}}


def lit_int(v):
    return {"expr": {"Literal": {"Value": f"{v}L"}}}


def col(table, column):
    return {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": column}}


def mea(name):
    assert any(x[0] == name for x in MEASURES), f"unknown measure {name}"
    return {"Measure": {"Expression": {"SourceRef": {"Entity": "_Measures"}}, "Property": name}}


def ref(field):
    k = next(iter(field))
    return f"{field[k]['Expression']['SourceRef']['Entity']}.{field[k]['Property']}"


def proj(field, display=None):
    p = {"field": field, "queryRef": ref(field), "nativeQueryRef": field[next(iter(field))]["Property"]}
    if display:
        p["displayName"] = display
    return p


def solid(color):
    """Colour from a hex string or from a measure (conditional formatting)."""
    return {"solid": {"color": lit(color) if isinstance(color, str) else {"expr": color}}}


def text_or_measure(v):
    return lit(v) if isinstance(v, str) else {"expr": v}


def plain_container(**over):
    """No card chrome: for elements that sit on the sidebar or overlay a tile."""
    o = {"background": [{"properties": {"show": lit(False)}}],
         "border": [{"properties": {"show": lit(False)}}],
         "dropShadow": [{"properties": {"show": lit(False)}}],
         "visualHeader": [{"properties": {"show": lit(False)}}],
         "title": [{"properties": {"show": lit(False)}}],
         "padding": [{"properties": {"top": lit(0), "bottom": lit(0), "left": lit(0), "right": lit(0)}}]}
    o.update(over)
    return o


class Page:
    def __init__(self, key, title, kind=None, width=1280, height=720):
        self.key, self.name, self.title = key, hid("page", key), title
        self.kind, self.width, self.height = kind, width, height
        self.visuals = []

    def add(self, vid, x, y, w, h, visual, extra=None):
        v = {"$schema": f"{SCHEMA}/item/report/definition/visualContainer/{V_VISUAL}/schema.json",
             "name": hid(self.key, vid),
             "position": {"x": round(x, 2), "y": round(y, 2), "z": len(self.visuals) * 100,
                          "height": round(h, 2), "width": round(w, 2), "tabOrder": len(self.visuals) * 100},
             "visual": visual}
        if extra:
            v.update(extra)
        self.visuals.append(v)


def visual(vtype, roles=None, title=None, subtitle=None, sort=None, objects=None, container=None,
           tooltip_page=None):
    v = {"visualType": vtype, "drillFilterOtherVisuals": True}
    if roles:
        v["query"] = {"queryState": {r: {"projections": [proj(f) if "Column" in f or "Measure" in f
                                                         else proj(*f) for f in fs]}
                                     for r, fs in roles.items()}}
        if sort:
            v["query"]["sortDefinition"] = {"sort": [{"field": f, "direction": d} for f, d in sort],
                                            "isDefaultSort": False}
    if objects:
        v["objects"] = objects
    vco = dict(container or {})
    if title is not None:
        vco.setdefault("title", [{"properties": {"show": lit(True), "text": text_or_measure(title)}}])
    if subtitle:
        vco["subTitle"] = [{"properties": {"show": lit(True), "text": lit(subtitle)}}]
    if tooltip_page:
        vco["visualTooltip"] = [{"properties": {"show": lit(True), "type": lit("ReportPage"),
                                                "section": lit(tooltip_page)}}]
    if vco:
        v["visualContainerObjects"] = vco
    return v


def textbox(paragraphs, container=None, align="left"):
    """paragraphs: list of lists of (text, size, color, bold) runs."""
    paras = []
    for runs in paragraphs:
        paras.append({"horizontalTextAlignment": align, "textRuns": [{"value": t, "textStyle": {
            "fontSize": f"{size}pt", "color": color, "fontFamily": FONT_SB if bold else FONT,
            **({"fontWeight": "bold"} if bold else {})}} for t, size, color, bold in runs]})
    return {"visualType": "textbox", "drillFilterOtherVisuals": True,
            "objects": {"general": [{"properties": {"paragraphs": paras}}]},
            "visualContainerObjects": container or plain_container()}


def panel(color, radius=0):
    """A coloured rectangle (sidebar, accents) made from an empty textbox container."""
    return {"visualType": "textbox", "drillFilterOtherVisuals": True,
            "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": ""}]}]}}]},
            "visualContainerObjects": plain_container(
                background=[{"properties": {"show": lit(True), "color": solid(color), "transparency": lit(0)}}],
                border=[{"properties": {"show": lit(radius > 0), "color": solid(color), "radius": lit(radius)}}])}


def card(measure, *, size=24, color=INK, display=None, millions=False, exact=False, title=None,
         container=None, font=FONT_SB):
    lab = {"color": solid(color), "fontSize": lit(size), "fontFamily": lit(font)}
    if millions:
        lab.update(labelDisplayUnits=lit(1000000), labelPrecision=lit_int(2))
    elif exact:
        lab.update(labelDisplayUnits=lit(1))
    return visual("card", {"Values": [(mea(measure), display)] if display else [mea(measure)]}, title=title,
                  objects={"labels": [{"properties": lab}],
                           "categoryLabels": [{"properties": {"show": lit(False)}}]},
                  container=container)


def series_colors(colors):
    return [{"properties": {"fill": solid(c)}, "selector": {"metadata": ref(mea(n))}} for n, c in colors]


def measure_fill(name):
    return [{"properties": {"fill": solid(mea(name))},
             "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}]}}]


def cf(measure_ref, *, back=None, font=None):
    """Conditional formatting on one value column of a table/matrix (field-value rule)."""
    props = {}
    if back:
        props["backColor"] = solid(mea(back))
    if font:
        props["fontColor"] = solid(mea(font))
    return {"properties": props,
            "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": measure_ref}}


def labels(show=True, **extra):
    extra.setdefault("labelPosition", "OutsideEnd")
    return [{"properties": {"show": lit(show), **{k: (lit(v) if not isinstance(v, dict) else v)
                                                   for k, v in extra.items()}}}]


# =========================================================================
# Layout
# =========================================================================
W, H = 1280, 720
SIDEBAR_W = 208
X0, X1 = 224, 1264          # content area
GAP = 12
NAV = [("overview", "Forecast Overview"), ("accuracy", "Forecast Accuracy"), ("drivers", "Sales Drivers")]
SLICERS = [(col("dim_store", "region"), "REGION", "region"),
           (col("dim_store", "format"), "STORE FORMAT", "format"),
           (col("dim_store", "store_name"), "STORE", "store")]
PAGE_NAMES = {k: hid("page", k) for k, _ in NAV}
PAGE_NAMES["store"] = hid("page", "store")
PAGE_NAMES["tooltip"] = hid("page", "tooltip")


def sidebar(p, active):
    p.add("sb_bg", 0, 0, SIDEBAR_W, H, panel(NAVY))
    p.add("sb_brand", 20, 22, 180, 52, textbox([
        [("CORVANE", 13, GOLD, True)],
        [("Demand Forecasting", 9, SLATE_2, False)]]))
    p.add("sb_rule", 20, 82, 168, 1, panel("#22395A"))
    p.add("sb_navlabel", 20, 94, 168, 16, textbox([[("DASHBOARDS", 7, "#7C8DA6", True)]]))
    for i, (key, label) in enumerate(NAV):
        y = 114 + i * 40
        is_active = key == active
        if is_active:
            p.add(f"nav_bg_{key}", 12, y, 184, 34, panel(NAVY_2, radius=8))
            p.add(f"nav_mark_{key}", 12, y + 8, 3, 18, panel(GOLD, radius=1))
        p.add(f"nav_label_{key}", 28, y + 8, 160, 20, textbox(
            [[(label, 10, WHITE if is_active else "#A9B6C9", is_active)]]))
        p.add(f"nav_{key}", 12, y, 184, 34, {
            "visualType": "actionButton", "drillFilterOtherVisuals": True,
            "objects": {
                "icon": [{"properties": {"show": lit(False)}}, {"properties": {"show": lit(False)}, "selector": {"id": "default"}}],
                "text": [{"properties": {"show": lit(False)}}, {"properties": {"show": lit(False)}, "selector": {"id": "default"}}],
                "fill": [{"properties": {"show": lit(False)}}, {"properties": {"show": lit(False)}, "selector": {"id": "default"}}],
                "outline": [{"properties": {"show": lit(False)}}, {"properties": {"show": lit(False)}, "selector": {"id": "default"}}]},
            "visualContainerObjects": {
                **plain_container(),
                "visualLink": [{"properties": {"show": lit(True), "type": lit("PageNavigation"),
                                               "navigationSection": lit(PAGE_NAMES[key])}}]}})
    y2 = 114 + len(NAV) * 40 + 10
    p.add("sb_rule2", 20, y2, 168, 1, panel("#22395A"))
    p.add("sb_filterlabel", 20, y2 + 12, 168, 16, textbox([[("FILTERS", 7, "#7C8DA6", True)]]))
    for i, (f, label, g) in enumerate(SLICERS):
        y = y2 + 32 + i * 62
        v = visual("slicer", {"Values": [(f, label)]}, objects={
            "data": [{"properties": {"mode": lit("Dropdown")}}],
            "header": [{"properties": {"show": lit(True), "fontColor": solid(MIST), "textSize": lit(8),
                                       "fontFamily": lit(FONT_SB)}}],
            "items": [{"properties": {"fontColor": solid(INK), "background": solid(WHITE), "textSize": lit(9)}}]},
            container=plain_container())
        v["syncGroup"] = {"groupName": g, "fieldChanges": True, "filterChanges": True}
        p.add(f"slicer_{g}", 20, y, 168, 54, v)
    p.add("sb_foot", 20, 650, 176, 56, textbox([
        [("Synthetic data · 60 stores · 2023 – 2025", 7, "#7C8DA6", False)],
        [("Ctrl + click a menu item in Desktop", 7, "#7C8DA6", False)],
        [("Right-click a store to drill through", 7, "#7C8DA6", False)]]))


def header(p, title):
    p.add("hdr_title", X0, 14, 620, 34, textbox([[(title, 18, INK, True)]]))
    p.add("hdr_context", X0, 46, 900, 22, visual(
        "card", {"Values": [mea("Blank Text")]},
        objects={"labels": [{"properties": {"fontSize": lit(1), "color": solid(CANVAS)}}],
                 "categoryLabels": [{"properties": {"show": lit(False)}}]},
        container=plain_container(title=[{"properties": {
            "show": lit(True), "text": {"expr": mea("Filter Context")}, "fontColor": solid(SLATE),
            "fontSize": lit(9), "fontFamily": lit(FONT), "alignment": lit("left")}}])))


def frame():
    """White rounded card with shadow (the tile background)."""
    return {"visualType": "textbox", "drillFilterOtherVisuals": True,
            "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": ""}]}]}}]},
            "visualContainerObjects": plain_container(
                background=[{"properties": {"show": lit(True), "color": solid(WHITE), "transparency": lit(0)}}],
                border=[{"properties": {"show": lit(True), "color": solid(LINE), "radius": lit(12)}}],
                dropShadow=[{"properties": {"show": lit(True), "color": solid(NAVY), "position": lit("Outer"),
                                            "preset": lit("Custom"), "transparency": lit(90), "shadowBlur": lit(14),
                                            "shadowDistance": lit(3), "shadowSpread": lit(0), "angle": lit(90)}}])}


def kpi_tiles(p, tiles, y=76, h=104):
    """tiles: (value measure, label, sub-measure, sub-colour measure or hex, number style)."""
    n = len(tiles)
    w = (X1 - X0 - (n - 1) * GAP) / n
    for i, (val, label, sub, sub_color, style) in enumerate(tiles):
        x = X0 + i * (w + GAP)
        p.add(f"kpi_{i}_frame", x, y, w, h, frame())
        p.add(f"kpi_{i}_rule", x + w / 2 - 14, y + 12, 28, 3, panel(GOLD))
        p.add(f"kpi_{i}_label", x + 8, y + 20, w - 16, 18,
              textbox([[(label.upper(), 7.5, SLATE, True)]], align="center"))
        p.add(f"kpi_{i}_value", x + 6, y + 38, w - 12, 40, card(
            val, size=22, millions=style == "M", exact=style == "N", container=plain_container()))
        is_hex = sub_color.startswith("#")
        sub_card = card(sub, size=8.5, font=FONT_SB, color=sub_color if is_hex else SLATE,
                        container=plain_container())
        if not is_hex:          # colour from a measure: teal = better, terracotta = worse
            sub_card["objects"]["labels"][0]["properties"]["color"] = solid(mea(sub_color))
        p.add(f"kpi_{i}_sub", x + 6, y + 78, w - 12, 20, sub_card)


# =========================================================================
# Pages
# =========================================================================
STORE = (col("dim_store", "store_name"), "Store")


def forecast_trend(title_measure, subtitle):
    return visual(
        "lineChart", {"Category": [(col("dim_date", "date"), "Date")],
                      "Y": [(mea("Actual Sales (Recent)"), "Actual"), (mea("Forecast"), "Forecast"),
                            (mea("Forecast P10"), "Low (P10)"), (mea("Forecast P90"), "High (P90)")]},
        title=mea(title_measure), subtitle=subtitle,
        objects={"dataPoint": series_colors([("Actual Sales (Recent)", NAVY), ("Forecast", GOLD),
                                             ("Forecast P10", "#E3D3A6"), ("Forecast P90", "#E3D3A6")]),
                 "lineStyles": [{"properties": {"strokeWidth": lit(2)}},
                                {"properties": {"strokeWidth": lit(3)}, "selector": {"metadata": ref(mea("Forecast"))}},
                                {"properties": {"lineStyle": lit("dashed"), "strokeWidth": lit(1.5)},
                                 "selector": {"metadata": ref(mea("Forecast P10"))}},
                                {"properties": {"lineStyle": lit("dashed"), "strokeWidth": lit(1.5)},
                                 "selector": {"metadata": ref(mea("Forecast P90"))}}],
                 "categoryAxis": [{"properties": {"axisType": lit("Scalar")}}]},
        tooltip_page=PAGE_NAMES["tooltip"])


def page_overview():
    p = Page("overview", "Forecast Overview")
    sidebar(p, "overview")
    header(p, "6-Week Sales Forecast  ·  1 Jan – 11 Feb 2026")
    kpi_tiles(p, [
        ("Forecast", "Forecast sales", "Forecast vs LY Label", "vs LY Color", "M"),
        ("Forecast P10", "Low case (P10)", "Note P10", SLATE, "M"),
        ("Forecast P90", "High case (P90)", "Note P90", SLATE, "M"),
        ("Sales Same Dates LY", "Same dates 2025", "Note LY", SLATE, "M"),
        ("WAPE Selected Model", "Forecast error (backtest)", "Error Reduction Label", GOOD, "")])
    p.add("trend", X0, 192, 676, 262, forecast_trend("Title Forecast Trend",
                                                       "Dashed lines: 8 in 10 outcomes should fall between them"))
    p.add("weeks", X0 + 676 + GAP, 192, X1 - X0 - 676 - GAP, 262, visual(
        "pivotTable", {"Rows": [(col("dim_date", "week_start"), "Week of")],
                       "Values": [(mea("Forecast"), "Forecast"), (mea("Sales Same Dates LY"), "2025"),
                                  (mea("Forecast vs LY %"), "vs 2025")]},
        title="Weekly outlook", subtitle="Promo weeks: 12 Jan, 26 Jan, 9 Feb",
        sort=[(col("dim_date", "week_start"), "Ascending")],
        objects={"values": [cf(ref(mea("Forecast vs LY %")), font="vs LY Color")]}))
    p.add("regions", X0, 466, 440, 238, visual(
        "clusteredBarChart", {"Category": [(col("dim_store", "region"), "Region")],
                              "Y": [(mea("Forecast"), "Forecast")],
                              "Tooltips": [mea("Forecast vs LY %"), mea("Stores")]},
        title="Forecast by region", subtitle="Where the next six weeks of sales come from",
        sort=[(mea("Forecast"), "Descending")],
        objects={"dataPoint": [{"properties": {"fill": solid(PRIMARY)}}],
                 "labels": labels(True, labelDisplayUnits=1000000, labelPrecision=lit_int(2))}))
    p.add("stores", X0 + 440 + GAP, 466, X1 - X0 - 440 - GAP, 238, visual(
        "tableEx", {"Values": [(mea("Store Forecast Rank"), "#"), STORE, (col("dim_store", "format"), "Format"),
                               (mea("Forecast"), "Forecast"), (mea("Forecast vs LY %"), "vs 2025"),
                               (mea("Store WAPE"), "Backtest error")]},
        title="Stores ranked by forecast", subtitle="Right-click a store → Drill through → Store Detail",
        sort=[(mea("Forecast"), "Descending")],
        objects={"values": [cf(ref(mea("Forecast vs LY %")), font="vs LY Color"),
                            cf(ref(mea("Store WAPE")), back="WAPE Heat")],
                 "columnWidth": [{"properties": {"value": lit(w)}, "selector": {"metadata": r}}
                                 for r, w in [(ref(mea("Store Forecast Rank")), 40),
                                              (ref(col("dim_store", "store_name")), 150)]]}))
    return p


def page_accuracy():
    p = Page("accuracy", "Forecast Accuracy")
    sidebar(p, "accuracy")
    header(p, "Forecast Accuracy  ·  rolling backtest")
    kpi_tiles(p, [
        ("WAPE Selected Model", "Ensemble error (WAPE)", "Error Reduction Label", GOOD, ""),
        ("WAPE Baseline", "Baseline error (WAPE)", "Baseline Label", SLATE, ""),
        ("MAPE Selected Model", "Ensemble MAPE", "MAPE Label", SLATE, ""),
        ("Bias Selected Model", "Ensemble bias", "Bias Label", SLATE, "")])
    MODEL = (col("fact_backtest", "model_label"), "Model")
    p.add("models", X0, 192, 420, 262, visual(
        "clusteredColumnChart", {"Category": [MODEL], "Y": [(mea("WAPE"), "WAPE")], "Tooltips": [mea("Bias %")]},
        title="Error by model (lower is better)", subtitle="Total absolute error ÷ total sales, open days",
        sort=[(col("fact_backtest", "model_label"), "Ascending")],
        objects={"dataPoint": measure_fill("Model Color"), "labels": labels(True, labelPrecision=lit_int(1))}))
    p.add("windows", X0 + 420 + GAP, 192, X1 - X0 - 420 - GAP, 262, visual(
        "pivotTable", {"Rows": [(col("fact_backtest", "backtest_window"), "Backtest window")],
                       "Columns": [MODEL], "Values": [(mea("WAPE"), "WAPE")]},
        title="Error by backtest window and model", subtitle="The baseline struggles when last year's promo calendar differs",
        objects={"values": [cf(ref(mea("WAPE")), back="WAPE Heat")]}))
    p.add("line", X0, 466, 620, 238, visual(
        "lineChart", {"Category": [(col("dim_date", "date"), "Date")],
                      "Y": [(mea("Backtest Actual"), "Actual"),
                            (mea("Forecast Selected Model (Backtest)"), "Ensemble"),
                            (mea("Forecast Baseline (Backtest)"), "Baseline")]},
        title=mea("Title Accuracy Trend"), subtitle="Each window was forecast before its data was seen",
        objects={"dataPoint": series_colors([("Backtest Actual", NAVY), ("Forecast Selected Model (Backtest)", GOLD),
                                             ("Forecast Baseline (Backtest)", COMPARE)]),
                 "lineStyles": [{"properties": {"strokeWidth": lit(2)}},
                                {"properties": {"lineStyle": lit("dashed"), "strokeWidth": lit(1.5)},
                                 "selector": {"metadata": ref(mea("Forecast Baseline (Backtest)"))}}],
                 "categoryAxis": [{"properties": {"axisType": lit("Scalar")}}]}))
    p.add("storeheat", X0 + 620 + GAP, 466, X1 - X0 - 620 - GAP, 238, visual(
        "pivotTable", {"Rows": [STORE], "Columns": [MODEL], "Values": [(mea("WAPE"), "WAPE")]},
        title="Error by store and model", subtitle="Teal = under 5%, red = over 9%",
        sort=[(col("dim_store", "store_name"), "Ascending")],
        objects={"values": [cf(ref(mea("WAPE")), back="WAPE Heat")]}))
    return p


def page_drivers():
    p = Page("drivers", "Sales Drivers")
    sidebar(p, "drivers")
    header(p, "What Drives Daily Sales")
    kpi_tiles(p, [
        ("Promo Lift Neighborhood", "Promo lift · Neighborhood", "Note Promo Neighborhood", SLATE, ""),
        ("Promo Lift Flagship", "Promo lift · Flagship", "Note Promo Flagship", SLATE, ""),
        ("Promo Lift Express", "Promo lift · Express", "Note Promo Express", SLATE, ""),
        ("Payday Lift", "Payday lift", "Note Payday", SLATE, ""),
        ("Competitor Hit", "Sales lost to a new competitor", "Note Competitor", SLATE, "")])
    p.add("effects", X0, 192, 520, 512, visual(
        "clusteredBarChart", {"Category": [(col("driver_effects", "effect"), "Effect")],
                              "Y": [(mea("Estimated Effect"), "Estimated effect")],
                              "Tooltips": [mea("True Effect (Simulated)"), mea("Effect CI Low"), mea("Effect CI High")]},
        title="Effect on daily sales, controlling for store, weekday, season and trend",
        subtitle="Fixed-effects regression on 62,555 store-days · chain-level estimates",
        sort=[(mea("Estimated Effect"), "Descending")],
        objects={"dataPoint": measure_fill("Effect Color"), "labels": labels(True, labelPrecision=lit_int(1)),
                 "categoryAxis": [{"properties": {"fontSize": lit(8), "maxMarginFactor": lit(45)}}]}))
    p.add("competitor", X0 + 520 + GAP, 192, X1 - X0 - 520 - GAP, 250, visual(
        "scatterChart", {"Category": [STORE], "X": [(mea("Competitor Distance"), "Distance to new competitor (m)")],
                         "Y": [(mea("Competitor Hit"), "Sales lost")]},
        title="New competitors: the closer, the bigger the hit", subtitle="12 stores with a competitor opening in 2024-25",
        objects={"dataPoint": [{"properties": {"fill": solid(BAD)}}],
                 "categoryLabels": [{"properties": {"show": lit(True), "fontSize": lit(7), "color": solid(SLATE)}}],
                 "categoryAxis": [{"properties": {"showAxisTitle": lit(True)}}],
                 "valueAxis": [{"properties": {"showAxisTitle": lit(True)}}]}))
    p.add("weekday", X0 + 520 + GAP, 454, X1 - X0 - 520 - GAP, 250, visual(
        "clusteredColumnChart", {"Category": [(col("dim_date", "weekday"), "Weekday")],
                                 "Series": [(col("dim_store", "format"), "Format")],
                                 "Y": [(mea("Avg Sales per Open Day"), "Avg sales per open day")]},
        title="Average sales per open day by weekday and format", subtitle="Express stores close on Sundays",
        sort=[(col("dim_date", "weekday"), "Ascending")]))
    return p


def page_store():
    p = Page("store", "Store Detail", kind="Drillthrough")
    sidebar(p, None)
    p.add("hdr_title", X0 + 48, 14, 760, 34, card("Title Store", size=1, container=plain_container(
        title=[{"properties": {"show": lit(True), "text": {"expr": mea("Title Store")}, "fontColor": solid(INK),
                               "fontSize": lit(18), "fontFamily": lit(FONT_SB), "alignment": lit("left")}}])))
    p.visuals[-1]["visual"]["objects"]["labels"][0]["properties"]["color"] = solid(CANVAS)
    p.add("back", X0, 16, 36, 30, {
        "visualType": "actionButton", "drillFilterOtherVisuals": True,
        "objects": {"icon": [{"properties": {"shapeType": lit("back"), "lineColor": solid(PRIMARY),
                                             "lineWeight": lit(2)}, "selector": {"id": "default"}}],
                    "fill": [{"properties": {"show": lit(True), "fillColor": solid(WHITE)}, "selector": {"id": "default"}}],
                    "outline": [{"properties": {"show": lit(False)}},
                                {"properties": {"show": lit(False)}, "selector": {"id": "default"}}]},
        "visualContainerObjects": {**plain_container(
            border=[{"properties": {"show": lit(True), "color": solid(LINE), "radius": lit(8)}}]),
            "visualLink": [{"properties": {"show": lit(True), "type": lit("Back")}}]}})
    tmp = Page("tmp", "")
    header(tmp, "")
    ctx = tmp.visuals[1]
    ctx["name"] = hid("store", "hdr_context")
    p.visuals.append(ctx)
    kpi_tiles(p, [
        ("Forecast", "Store forecast", "Forecast vs LY Label", "vs LY Color", ""),
        ("Store WAPE", "Backtest error (WAPE)", "Error Reduction Label", GOOD, ""),
        ("Avg Sales per Open Day", "Avg sales per open day", "Note History", SLATE, ""),
        ("Avg Basket", "Average basket", "Note History", SLATE, "")])
    p.add("trend", X0, 192, 676, 262, forecast_trend("Title Forecast Trend", "Actual Oct-Dec 2025, forecast with P10-P90"))
    p.add("profile", X0 + 676 + GAP, 192, X1 - X0 - 676 - GAP, 262, visual(
        "tableEx", {"Values": [(col("dim_store", "format"), "Format"), (col("dim_store", "region"), "Region"),
                               (col("dim_store", "assortment"), "Assortment"),
                               (col("dim_store", "loyalty_programme"), "Loyalty"),
                               (col("dim_store", "new_competitor"), "New competitor")]},
        title="Store profile", subtitle="Attributes that shape the forecast"))
    p.add("bt", X0, 466, X1 - X0, 238, visual(
        "lineChart", {"Category": [(col("dim_date", "date"), "Date")],
                      "Y": [(mea("Backtest Actual"), "Actual"),
                            (mea("Forecast Selected Model (Backtest)"), "Ensemble"),
                            (mea("Forecast Baseline (Backtest)"), "Baseline")]},
        title="How well this store was forecast in the three backtests", subtitle="Actual vs ensemble vs baseline",
        objects={"dataPoint": series_colors([("Backtest Actual", NAVY), ("Forecast Selected Model (Backtest)", GOLD),
                                             ("Forecast Baseline (Backtest)", COMPARE)]),
                 "lineStyles": [{"properties": {"strokeWidth": lit(2)}},
                                {"properties": {"lineStyle": lit("dashed"), "strokeWidth": lit(1.5)},
                                 "selector": {"metadata": ref(mea("Forecast Baseline (Backtest)"))}}],
                 "categoryAxis": [{"properties": {"axisType": lit("Scalar")}}]}))
    return p


def page_tooltip():
    p = Page("tooltip", "Tooltip · Day", kind="Tooltip", width=320, height=220)
    p.add("bg", 0, 0, 320, 220, panel(WHITE))
    p.add("title", 14, 10, 292, 30, card("Title Tooltip", size=1, container=plain_container(
        title=[{"properties": {"show": lit(True), "text": {"expr": mea("Title Tooltip")}, "fontColor": solid(INK),
                               "fontSize": lit(12), "fontFamily": lit(FONT_SB), "alignment": lit("left")}}])))
    p.visuals[-1]["visual"]["objects"]["labels"][0]["properties"]["color"] = solid(WHITE)
    for i, (mname, label) in enumerate([("Forecast", "FORECAST"), ("Actual Sales", "ACTUAL"),
                                        ("Forecast P10", "LOW (P10)"), ("Forecast P90", "HIGH (P90)")]):
        x, y = 14 + (i % 2) * 150, 46 + (i // 2) * 84
        p.add(f"t{i}", x, y, 142, 76, card(mname, size=15, title=label))
    return p


PAGES = [page_overview, page_accuracy, page_drivers, page_store, page_tooltip]
DRILL_FIELD = col("dim_store", "store_name")


def build_report():
    if RP.exists():
        shutil.rmtree(RP)
    write_json(RP / "definition.pbir", {
        "$schema": f"{SCHEMA}/item/report/definitionProperties/2.0.0/schema.json",
        "version": "4.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}}})
    write_json(RP / ".platform", {
        "$schema": f"{SCHEMA}/gitIntegration/platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Report", "displayName": NAME},
        "config": {"version": "2.0", "logicalId": gid("report")}})
    base = RP / "StaticResources" / "SharedResources" / "BaseThemes" / f"{BASE_THEME}.json"
    base.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(THEME_SRC, base)
    write_json(RP / "StaticResources" / "RegisteredResources" / CUSTOM_THEME, THEME)
    write_json(PBI / "theme" / CUSTOM_THEME, THEME)        # standalone copy, importable in any report
    version = {"visual": V_VISUAL, "report": V_REPORT, "page": V_PAGE}
    d = RP / "definition"
    write_json(d / "version.json", {
        "$schema": f"{SCHEMA}/item/report/definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    write_json(d / "report.json", {
        "$schema": f"{SCHEMA}/item/report/definition/report/{V_REPORT}/schema.json",
        "themeCollection": {
            "baseTheme": {"name": BASE_THEME, "reportVersionAtImport": version, "type": "SharedResources"},
            "customTheme": {"name": CUSTOM_THEME, "reportVersionAtImport": version, "type": "RegisteredResources"}},
        "resourcePackages": [
            {"name": "SharedResources", "type": "SharedResources",
             "items": [{"name": BASE_THEME, "path": f"BaseThemes/{BASE_THEME}.json", "type": "BaseTheme"}]},
            {"name": "RegisteredResources", "type": "RegisteredResources",
             "items": [{"name": CUSTOM_THEME, "path": CUSTOM_THEME, "type": "CustomTheme"}]}],
        "objects": {"outspacePane": [{"properties": {"expanded": lit(False)}}]},
        "settings": {"useStylableVisualContainerHeader": True, "defaultDrillFilterOtherVisuals": True,
                     "allowChangeFilterTypes": True, "useEnhancedTooltips": True,
                     "exportDataMode": "AllowSummarized"}})
    pages = [f() for f in PAGES]
    write_json(d / "pages" / "pages.json", {
        "$schema": f"{SCHEMA}/item/report/definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": [p.name for p in pages], "activePageName": pages[0].name})
    for p in pages:
        page = {"$schema": f"{SCHEMA}/item/report/definition/page/{V_PAGE}/schema.json",
                "name": p.name, "displayName": p.title, "displayOption": "FitToPage",
                "height": p.height, "width": p.width}
        if p.kind == "Drillthrough":
            fname, pname = hid("filter", "store"), hid("param", "store")
            page.update({
                "type": "Drillthrough", "visibility": "HiddenInViewMode",
                "pageBinding": {"name": hid("binding", "store"), "type": "Drillthrough",
                                "parameters": [{"name": pname, "boundFilter": fname,
                                                "fieldExpr": DRILL_FIELD}]},
                "filterConfig": {"filters": [{"name": fname, "field": DRILL_FIELD,
                                              "type": "Categorical"}]}})
        elif p.kind == "Tooltip":
            page.update({"type": "Tooltip", "visibility": "HiddenInViewMode",
                         "pageBinding": {"name": hid("binding", "tooltip"), "type": "Tooltip",
                                         "parameters": []}})
        write_json(d / "pages" / p.name / "page.json", page)
        for v in p.visuals:
            write_json(d / "pages" / p.name / "visuals" / v["name"] / "visual.json", v)
    return pages


if __name__ == "__main__":
    build_semantic_model()
    pages = build_report()
    write_json(PBI / f"{NAME}.pbip", {
        "$schema": f"{SCHEMA}/pbip/pbipProperties/1.0.0/schema.json", "version": "1.0",
        "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}})
    write(PBI / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")
    print(f"wrote {PBI / (NAME + '.pbip')}")
    print(f"  model : {len(TABLES) + 1} tables, {len(MEASURES)} measures "
          f"({sum(1 for x in MEASURES if not x[4])} visible), {len(RELATIONSHIPS)} relationships")
    print(f"  report: {len(pages)} pages, {sum(len(p.visuals) for p in pages)} visuals")
