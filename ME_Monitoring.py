#!/usr/bin/env python
# coding: utf-8

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime, timedelta
import snowflake.connector
import numpy as np
import os
import json
from pathlib import Path

# Set dark theme as default
st.markdown("""
<style>
    .stApp {
        color-scheme: dark;
    }
</style>
""", unsafe_allow_html=True)

st.set_page_config(page_title='ME Monitoring Snowflake',
                  page_icon=":chart_with_upwards_trend:",
                  layout="wide",
                  initial_sidebar_state="expanded",
                  menu_items=None)


def _get_snowflake_conn():
    """Return an open Snowflake connection using secrets."""
    if "snowflake" not in st.secrets:
        raise Exception("No Snowflake secrets configured")
    conn_params = {
        "account": st.secrets["snowflake"]["account"],
        "user": st.secrets["snowflake"]["user"],
        "role": st.secrets["snowflake"]["role"],
        "warehouse": st.secrets["snowflake"]["warehouse"],
        "database": st.secrets["snowflake"]["database"],
        "schema": st.secrets["snowflake"]["schema"],
    }
    authenticator = st.secrets["snowflake"].get("authenticator", None)
    password = st.secrets["snowflake"].get("password", None)
    if authenticator == "externalbrowser":
        conn_params["authenticator"] = "externalbrowser"
    elif authenticator == "programmatic_access_token":
        if not password:
            raise Exception("PAT token missing from secrets")
        conn_params["authenticator"] = "programmatic_access_token"
        conn_params["password"] = password
    elif password:
        conn_params["password"] = password
    else:
        raise Exception("No valid authentication configured in secrets")
    return snowflake.connector.connect(**conn_params)


def _run_query(conn, query, params=None):
    """Execute a query and return a DataFrame, then close the cursor."""
    cursor = conn.cursor()
    cursor.execute(query, params or ())
    columns = [desc[0] for desc in cursor.description]
    data = cursor.fetchall()
    cursor.close()
    return pd.DataFrame(data, columns=columns)


ME_ATHLETES = [
    "Aaron Gate",
    "Keegan Hornblow",
    "Marshall Erwood",
    "Nicholas Kergozou De La Boessiere",
    "Thomas Sexton",
]
WE_ATHLETES = [
    "Ally Wollaston",
    "Bryony Botha",
    "Emily Shearman",
    "Samantha Donnelly",
]


def _default_periods_path():
    cache_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache"))
    return cache_root / "ME_Monitoring" / "default_periods.json"


def _load_default_periods():
    try:
        saved = json.loads(_default_periods_path().read_text(encoding="utf-8"))
        return [
            (date.fromisoformat(period["start"]), date.fromisoformat(period["end"]))
            for period in saved.get("periods", [])
        ]
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return []


def _save_default_periods(periods):
    path = _default_periods_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = {
        "periods": [
            {"start": start.isoformat(), "end": end.isoformat()}
            for start, end in periods
        ]
    }
    path.write_text(json.dumps(saved, indent=2), encoding="utf-8")


def _reset_summary_periods():
    st.session_state["summary_periods"] = _load_default_periods()
    for key in list(st.session_state):
        if key.startswith("summary_period_dates_"):
            del st.session_state[key]


def get_athlete_list(team):
    return ME_ATHLETES if team == "ME" else WE_ATHLETES


@st.cache_data
def load_athlete_data(athlete, weeks):
    """Fetch only the required athlete's data, limited to weeks+8 weeks for rolling averages."""
    conn = _get_snowflake_conn()
    try:
        query = """
            SELECT 
            USER_NAME_FIXED, WORKOUT_TYPE, START_TIME,
            POWER_ZONE_LABEL, POWER_ZONE_MINIMUM, POWER_ZONE_MAXIMUM,
            POWER_ZONE_SECONDS, DURATION_MINS, TSS, ENERGY,
            TOTAL_TIME_PLANNED, ENERGY_PLANNED, TSS_PLANNED,
            DESCRIPTION
            FROM TRAINING_PEAKS_CYCLING_VW
            WHERE USER_NAME_FIXED = %s
            
              AND START_TIME >= DATEADD(week, %s, CURRENT_DATE())
            ORDER BY START_TIME DESC
        """
        # Fetch weeks + 8 extra so rolling-average calculations have enough history
        df = _run_query(conn, query, (athlete, -(weeks + 8)))
    finally:
        conn.close()

    if df.empty:
        raise Exception(f"No data found for athlete: {athlete}")

    st_col = pd.to_datetime(df["START_TIME"], errors="coerce")
    if st_col.dt.tz is not None:
        st_col = st_col.dt.tz_convert(None)
    df["START_TIME"] = st_col
    return df


@st.cache_data
def load_period_data(athletes, start_date, end_date):
    """Fetch workout-level records across the selected summary periods."""
    conn = _get_snowflake_conn()
    try:
        placeholders = ", ".join(["%s"] * len(athletes))
        query = f"""
            SELECT USER_NAME_FIXED, WORKOUT_TYPE, START_TIME,
                   DURATION_MINS, TSS, ENERGY
            FROM TRAINING_PEAKS_CYCLING_VW
            WHERE USER_NAME_FIXED IN ({placeholders})
              AND START_TIME >= %s
              AND START_TIME < %s
            ORDER BY START_TIME DESC
        """
        params = (*athletes, start_date, end_date + timedelta(days=1))
        df = _run_query(conn, query, params)
    finally:
        conn.close()

    if not df.empty:
        start_times = pd.to_datetime(df["START_TIME"], errors="coerce")
        if start_times.dt.tz is not None:
            start_times = start_times.dt.tz_convert(None)
        df["START_TIME"] = start_times
    return df


@st.cache_data
def load_compare_data(athletes, start_date, end_date):
    """Fetch workout and power-zone rows for two comparison periods."""
    conn = _get_snowflake_conn()
    try:
        placeholders = ", ".join(["%s"] * len(athletes))
        query = f"""
            SELECT USER_NAME_FIXED, WORKOUT_TYPE, START_TIME,
                   POWER_ZONE_LABEL, POWER_ZONE_MINIMUM, POWER_ZONE_MAXIMUM,
                   POWER_ZONE_SECONDS, DURATION_MINS, TSS, ENERGY
            FROM TRAINING_PEAKS_CYCLING_VW
            WHERE USER_NAME_FIXED IN ({placeholders})
              AND START_TIME >= %s
              AND START_TIME < %s
            ORDER BY START_TIME DESC
        """
        params = (*athletes, start_date, end_date + timedelta(days=1))
        df = _run_query(conn, query, params)
    finally:
        conn.close()

    if not df.empty:
        start_times = pd.to_datetime(df["START_TIME"], errors="coerce")
        if start_times.dt.tz is not None:
            start_times = start_times.dt.tz_convert(None)
        df["START_TIME"] = start_times
    return df


def build_period_summary(df, athletes, periods, bike_only=False):
    """Build average-per-week and total summaries for user-selected periods."""
    if df.empty:
        return pd.DataFrame()

    workout_rows = df[df["DURATION_MINS"].notna()].copy()
    workout_rows = workout_rows[workout_rows["USER_NAME_FIXED"].isin(athletes)]
    labels = {
        "Nicholas Kergozou De La Boessiere": "Kergy",
        "Thomas Sexton": "Tom",
    }
    metrics = ["Hours", "TSS", "TSS/Hr", "ATLAv", "kJ", "Rides", "Gym"]
    period_labels = [
        f"Period {index + 1} ({start_date:%d %b %Y} - {end_date:%d %b %Y})"
        for index, (start_date, end_date) in enumerate(periods)
    ]
    rows = []
    if workout_rows.empty:
        return pd.DataFrame()

    athletes_with_data = [
        athlete for athlete in athletes
        if workout_rows["USER_NAME_FIXED"].eq(athlete).any()
    ]
    for athlete in athletes_with_data:
        athlete_data = workout_rows[workout_rows["USER_NAME_FIXED"] == athlete]
        for period_index, (start_date, end_date) in enumerate(periods):
            period_days = (end_date - start_date).days + 1
            period_weeks = period_days / 7
            period_data = athlete_data[
                athlete_data["START_TIME"].between(
                    pd.Timestamp(start_date), pd.Timestamp(end_date) + pd.Timedelta(days=1), inclusive="left"
                )
            ]
            metric_data = period_data
            if bike_only:
                metric_data = period_data[period_data["WORKOUT_TYPE"].isin(["Bike", "MTB"])]

            total_hours = metric_data["DURATION_MINS"].sum() / 60
            total_tss = metric_data["TSS"].sum()
            total_kj = metric_data["ENERGY"].sum()
            ride_count = metric_data["WORKOUT_TYPE"].isin(["Bike", "MTB"]).sum()
            gym_count = period_data["WORKOUT_TYPE"].eq("Strength").sum()
            period_label = period_labels[period_index]

            rows.append({
                "Athlete": labels.get(athlete, athlete.split()[0]),
                "Period": "Avg / week",
                "Selected period": period_label,
                "Hours": total_hours / period_weeks,
                "TSS": total_tss / period_weeks,
                "TSS/Hr": total_tss / total_hours if total_hours else np.nan,
                "ATLAv": total_tss / period_weeks / 7,
                "kJ": total_kj / period_weeks,
                "Rides": ride_count / period_weeks,
                "Gym": gym_count,
            })
            rows.append({
                "Athlete": labels.get(athlete, athlete.split()[0]),
                "Period": "Period total",
                "Selected period": period_label,
                "Hours": total_hours,
                "TSS": total_tss,
                "TSS/Hr": np.nan,
                "ATLAv": np.nan,
                "kJ": total_kj,
                "Rides": ride_count,
                "Gym": np.nan,
            })

    if not rows:
        return pd.DataFrame()
    summary = pd.DataFrame(rows).pivot(
        index=["Athlete", "Period"], columns="Selected period", values=metrics
    )
    summary = summary.swaplevel(0, 1, axis=1)
    ordered_columns = []
    for period_index, period_label in enumerate(period_labels):
        ordered_columns.extend((period_label, metric) for metric in metrics)
        if period_index < len(period_labels) - 1:
            spacer_label = " " * (period_index + 1)
            ordered_columns.append((spacer_label, spacer_label))
    return summary.reindex(
        columns=pd.MultiIndex.from_tuples(ordered_columns, names=summary.columns.names)
    )


def build_compare_metrics(df, athlete, periods):
    """Calculate average-week metrics and power-zone distributions by period."""
    athlete_rows = df[df["USER_NAME_FIXED"].eq(athlete)]
    results = []
    for start_date, end_date in periods:
        period_weeks = ((end_date - start_date).days + 1) / 7
        period_rows = athlete_rows[
            athlete_rows["START_TIME"].between(
                pd.Timestamp(start_date),
                pd.Timestamp(end_date) + pd.Timedelta(days=1),
                inclusive="left",
            )
        ]
        workouts = period_rows[period_rows["DURATION_MINS"].notna()]
        strength = workouts[workouts["WORKOUT_TYPE"].eq("Strength")]
        zone_rows = period_rows[
            period_rows["POWER_ZONE_LABEL"].notna()
            & period_rows["POWER_ZONE_SECONDS"].notna()
        ]
        zone_minutes = (
            zone_rows.groupby("POWER_ZONE_LABEL")["POWER_ZONE_SECONDS"].sum()
            .div(60 * period_weeks)
        )
        zone_total = zone_minutes.sum()

        results.append({
            "Training Time": workouts["DURATION_MINS"].sum() / 60 / period_weeks,
            "TSS": workouts["TSS"].sum() / period_weeks,
            "Energy (kJ)": workouts["ENERGY"].sum() / 1000 / period_weeks,
            "Strength": strength["DURATION_MINS"].sum() / 60 / period_weeks,
            "Power Zones": zone_minutes,
            "Power Zones %": zone_minutes.div(zone_total).mul(100) if zone_total else zone_minutes,
        })
    return results


def build_compare_weekly_metrics(df, athlete, period, metric):
    """Return weekly totals, aligned to week numbers within the selected period."""
    start_date, end_date = period
    period_start = pd.Timestamp(start_date)
    period_end = pd.Timestamp(end_date) + pd.Timedelta(days=1)
    period_days = (end_date - start_date).days + 1
    week_count = (period_days + 6) // 7

    workouts = df[
        df["USER_NAME_FIXED"].eq(athlete)
        & df["START_TIME"].between(period_start, period_end, inclusive="left")
        & df["DURATION_MINS"].notna()
    ].copy()
    if metric == "Strength":
        workouts = workouts[workouts["WORKOUT_TYPE"].eq("Strength")]
        value_column, divisor = "DURATION_MINS", 60
    else:
        value_column, divisor = {
            "Training Time": ("DURATION_MINS", 60),
            "TSS": ("TSS", 1),
            "Energy (kJ)": ("ENERGY", 1000),
        }[metric]

    week_indices = (
        (pd.to_datetime(workouts["START_TIME"]) - period_start).dt.days // 7
    )
    workouts["WEEK_INDEX"] = week_indices
    weekly_values = workouts.groupby("WEEK_INDEX")[value_column].sum()
    return weekly_values.reindex(range(week_count), fill_value=0) / divisor


def _same_date_previous_year(value):
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return value.replace(year=value.year - 1, day=28)


def _athlete_hero_periods(today):
    periods = []
    for label, days in [
        ("Last 7 days", 7),
        ("Last 6 weeks", 42),
        ("Last 3 months", 90),
        ("Last year", 365),
    ]:
        current_start = today - timedelta(days=days - 1)
        previous_end = current_start - timedelta(days=1)
        periods.append({
            "label": label,
            "current": (current_start, today),
            "previous": (
                previous_end - timedelta(days=days - 1),
                previous_end,
            ),
            "year_ago": (
                _same_date_previous_year(current_start),
                _same_date_previous_year(today),
            ),
        })
    return periods


def _athlete_period_metric(data, metric, period, bike_only):
    start_date, end_date = period
    period_rows = data[
        data["START_TIME"].between(
            pd.Timestamp(start_date),
            pd.Timestamp(end_date) + pd.Timedelta(days=1),
            inclusive="left",
        )
    ]
    if metric in ("Power Zones", "Power Zones %"):
        zone_rows = period_rows[
            period_rows["POWER_ZONE_LABEL"].notna()
            & period_rows["POWER_ZONE_SECONDS"].notna()
        ]
        if bike_only:
            zone_rows = zone_rows[zone_rows["WORKOUT_TYPE"].isin(["Bike", "MTB"])]
        zone_seconds = zone_rows.groupby("POWER_ZONE_LABEL")["POWER_ZONE_SECONDS"].sum()
        if metric == "Power Zones %":
            total_seconds = zone_seconds.sum()
            return zone_seconds.div(total_seconds).mul(100) if total_seconds else zone_seconds
        return zone_seconds.sum() / 60

    workouts = period_rows[period_rows["DURATION_MINS"].notna()]
    if metric == "Strength":
        workouts = workouts[workouts["WORKOUT_TYPE"].eq("Strength")]
        return workouts["DURATION_MINS"].sum() / 60
    if bike_only:
        workouts = workouts[workouts["WORKOUT_TYPE"].isin(["Bike", "MTB"])]
    if metric == "Training Time":
        return workouts["DURATION_MINS"].sum() / 60
    if metric == "TSS":
        return workouts["TSS"].sum()
    if metric == "Energy (kJ)":
        return workouts["ENERGY"].sum() / 1000
    raise ValueError(f"Unsupported athlete hero metric: {metric}")


def render_athlete_hero_tiles(data, metric, bike_only, today):
    if data.empty:
        return

    st.subheader("Weekly averages")
    hero_periods = _athlete_hero_periods(today)
    columns = st.columns(4)
    for column, period in zip(columns, hero_periods):
        current = _athlete_period_metric(data, metric, period["current"], bike_only)
        previous = _athlete_period_metric(data, metric, period["previous"], bike_only)
        year_ago = _athlete_period_metric(data, metric, period["year_ago"], bike_only)

        if metric == "Power Zones %":
            zone = current.idxmax() if not current.empty else None
            current_value = current.get(zone, 0) if zone is not None else 0
            previous_value = previous.get(zone, 0) if zone is not None else 0
            year_ago_value = year_ago.get(zone, 0) if zone is not None else 0
            display_value = f"{zone}: {current_value:.1f}%" if zone is not None else "No zone data"
            unit = ""
        else:
            current_value = current
            previous_value = previous
            year_ago_value = year_ago
            unit = {
                "Training Time": "hours",
                "TSS": "",
                "Energy (kJ)": "kJ",
                "Strength": "hours",
                "Power Zones": "min",
            }[metric]

        def _format_number(value):
            number = f"{value:,.1f}"
            if metric == "Power Zones" and value >= 10000:
                number = f"{value / 1000:.1f}k"
            return number

        def _format_total(value):
            return f"{_format_number(value)} {unit}".strip()

        def _format_weekly_summary(value, period_weeks):
            weekly_unit = {
                "Training Time": "h/wk",
                "TSS": "",
                "Energy (kJ)": "kJ/wk",
                "Strength": "h/wk",
                "Power Zones": "min/wk",
            }[metric]
            total_unit = {
                "Training Time": "h",
                "TSS": "",
                "Energy (kJ)": "kJ",
                "Strength": "h",
                "Power Zones": "min",
            }[metric]
            weekly_label = f"{_format_number(value / period_weeks)} {weekly_unit}".strip()
            total_label = f"{_format_number(value)} {total_unit}".strip()
            return f"{weekly_label} ({total_label})"

        if metric != "Power Zones %":
            if period["label"] in ("Last 6 weeks", "Last 3 months", "Last year"):
                current_start, current_end = period["current"]
                period_weeks = ((current_end - current_start).days + 1) / 7
                display_value = _format_weekly_summary(current_value, period_weeks)
            else:
                display_value = (
                    _format_number(current_value)
                    if metric == "Power Zones"
                    else _format_total(current_value)
                )

        def _shift_indicator(reference):
            if not reference:
                return ":gray[\u2014 n/a]"
            shift = (current_value - reference) / abs(reference) * 100
            if shift > 0:
                return f":green[\u2191 {shift:+.1f}%]"
            if shift < 0:
                return f":red[\u2193 {shift:+.1f}%]"
            return ":gray[\u2192 0.0%]"

        def _comparison_value(value, comparison_period):
            if metric == "Power Zones %":
                return f"{zone}: {value:.1f}%"
            start_date, end_date = comparison_period
            period_weeks = ((end_date - start_date).days + 1) / 7
            return _format_weekly_summary(value, period_weeks)

        current_start, current_end = period["current"]
        previous_start, previous_end = period["previous"]
        year_ago_start, year_ago_end = period["year_ago"]
        with column:
            with st.container(border=True):
                metric_label = (
                    f"{period['label']} (min)"
                    if metric == "Power Zones"
                    else period["label"]
                )
                st.metric(metric_label, display_value)
                st.caption(f"{current_start:%d %b %Y} - {current_end:%d %b %Y}")
                st.caption(
                    f"vs {previous_start:%d %b %Y} - {previous_end:%d %b %Y}: "
                    f"{_comparison_value(previous_value, period['previous'])} "
                    f"({_shift_indicator(previous_value)})"
                )
                st.caption(
                    f"vs {year_ago_start:%d %b %Y} - {year_ago_end:%d %b %Y}: "
                    f"{_comparison_value(year_ago_value, period['year_ago'])} "
                    f"({_shift_indicator(year_ago_value)})"
                )


# ── UI components ──────────────────────────────────────────────────────────────
selected_team = st.radio(
    "Team", ["ME", "WE"], horizontal=True, key="athlete_team"
)
available_athletes = get_athlete_list(selected_team)
if st.session_state.get("summary_athletes") is not None and any(
    athlete not in available_athletes
    for athlete in st.session_state["summary_athletes"]
):
    st.session_state["summary_athletes"] = list(available_athletes)
if st.session_state.get("athlete_summary_selection") not in available_athletes:
    st.session_state["athlete_summary_selection"] = available_athletes[0]
if st.session_state.get("compare_athlete_1") not in available_athletes:
    st.session_state["compare_athlete_1"] = available_athletes[0]
if st.session_state.get("compare_athlete_2") not in available_athletes:
    st.session_state["compare_athlete_2"] = available_athletes[1]
compare_configuration = st.session_state.get("compare_configuration")
if compare_configuration and any(
    athlete not in available_athletes for athlete in compare_configuration[:2]
):
    del st.session_state["compare_configuration"]
squad_tab, athlete_tab, compare_tab = st.tabs(
    ["Squad summary", "Athlete Summary", "Compare"]
)

with squad_tab:
    selected_athlete = "Summary"
    bike_only = st.toggle("Bike only", value=False, key="summary_bike_only")

    # ── User-defined summary periods ───────────────────────────────────────────────
    today = pd.Timestamp.now(tz="Pacific/Auckland").date()
    summary_athletes = tuple(available_athletes)

    if selected_athlete == "Summary":
        st.subheader("Summary")
        selected_summary_athletes = st.multiselect(
            "Athletes",
            options=list(summary_athletes),
            default=list(summary_athletes),
            key="summary_athletes",
        )
        if "summary_periods" not in st.session_state:
            st.session_state["summary_periods"] = _load_default_periods()
        summary_periods = st.session_state["summary_periods"]

        if not summary_periods:
            initial_start = today - timedelta(days=83)
            with st.form("select_first_period"):
                date_column, button_column = st.columns([4, 1])
                with date_column:
                    selected_dates = st.date_input(
                        "Select dates",
                        value=(initial_start, today),
                        key="summary_period_dates_0",
                    )
                with button_column:
                    st.write("")
                    select_period = st.form_submit_button("Select period")

            if select_period:
                if isinstance(selected_dates, (tuple, list)) and len(selected_dates) == 2:
                    st.session_state["summary_periods"].append(tuple(selected_dates))
                    st.rerun()
                st.warning("Select both a start date and an end date.")

        if summary_periods:
            if not selected_summary_athletes:
                st.info("Select at least one athlete to show summary data.")
            else:
                try:
                    query_start = min(period[0] for period in summary_periods)
                    query_end = max(period[1] for period in summary_periods)
                    with st.spinner("Loading summary data..."):
                        period_data = load_period_data(
                            tuple(selected_summary_athletes), query_start, query_end
                        )
                    period_summary = build_period_summary(
                        period_data, selected_summary_athletes, summary_periods, bike_only
                    )
                    if period_summary.empty:
                        st.info("No data found for the selected periods.")
                    else:
                        chart_metric = st.selectbox(
                            "Longitudinal metric",
                            options=["Hours", "TSS", "TSS/Hr", "ATLAv", "kJ", "Rides", "Gym"],
                            key="summary_chart_metric",
                        )
                        average_summary = period_summary.xs("Avg / week", level="Period")
                        chart_rows = []
                        for period_index, (start_date, end_date) in enumerate(summary_periods):
                            period_label = (
                                f"Period {period_index + 1} "
                                f"({start_date:%d %b %Y} - {end_date:%d %b %Y})"
                            )
                            metric_column = (period_label, chart_metric)
                            for athlete, value in average_summary[metric_column].items():
                                if pd.notna(value):
                                    chart_rows.append({
                                        "Period": f"Period {period_index + 1}",
                                        "Date range": period_label,
                                        "Athlete": athlete,
                                        chart_metric: value,
                                    })

                        chart = px.line(
                            pd.DataFrame(chart_rows),
                            x="Period",
                            y=chart_metric,
                            color="Athlete",
                            markers=True,
                            hover_data=["Date range"],
                        )
                        chart.update_layout(
                            xaxis_title="Period",
                            yaxis_title=chart_metric,
                            legend_title="Athlete",
                        )
                        st.plotly_chart(chart, width="stretch")

                        period_summary = period_summary.reset_index().fillna("")
                        period_styler = period_summary.style.format(precision=1, na_rep="")
                        if len(summary_periods) > 1:
                            metric_names = ["Hours", "TSS", "TSS/Hr", "ATLAv", "kJ", "Rides", "Gym"]

                            def _period_comparison_colors(row):
                                colors = pd.Series("", index=row.index, dtype=object)
                                for metric in metric_names:
                                    metric_columns = [
                                        column for column in row.index
                                        if isinstance(column, tuple) and column[1] == metric
                                    ]
                                    values = pd.to_numeric(row.loc[metric_columns], errors="coerce").dropna()
                                    if values.empty:
                                        continue

                                    minimum = values.min()
                                    maximum = values.max()
                                    for column, value in values.items():
                                        progress = 1 if maximum == minimum else (value - minimum) / (maximum - minimum)
                                        red = round(248 + (99 - 248) * progress)
                                        green = round(105 + (190 - 105) * progress)
                                        blue = round(107 + (123 - 107) * progress)
                                        colors.loc[column] = f"background-color: #{red:02x}{green:02x}{blue:02x}"
                                return colors

                            period_styler = period_styler.apply(_period_comparison_colors, axis=1)
                        st.dataframe(
                            period_styler,
                            hide_index=True,
                        )
                except Exception as e:
                    st.error(f"Failed to load summary data: {e}")

            last_start, last_end = summary_periods[-1]
            period_length = (last_end - last_start).days + 1
            next_start = last_end + timedelta(days=1)
            next_end = next_start + timedelta(days=period_length - 1)
            with st.form(f"add_period_form_{len(summary_periods)}"):
                date_column, button_column = st.columns([4, 1])
                with date_column:
                    next_dates = st.date_input(
                        "Next period dates",
                        value=(next_start, next_end),
                        key=f"summary_period_dates_{len(summary_periods)}",
                    )
                with button_column:
                    st.write("")
                    add_period = st.form_submit_button("Add period")

            if add_period:
                if isinstance(next_dates, (tuple, list)) and len(next_dates) == 2:
                    st.session_state["summary_periods"].append(tuple(next_dates))
                    st.rerun()
                st.warning("Select both a start date and an end date.")

            action_columns = st.columns(2)
            with action_columns[0]:
                if st.button("Set default periods", key="set_default_summary_periods"):
                    try:
                        _save_default_periods(summary_periods)
                        st.success("Default periods saved to your user cache.")
                    except OSError as error:
                        st.error(f"Could not save default periods: {error}")
            with action_columns[1]:
                if st.button(
                    "Reset periods",
                    key="reset_summary_periods",
                    on_click=_reset_summary_periods,
                ):
                    if _load_default_periods():
                        st.success("Periods reset to your saved defaults.")
                    else:
                        st.info("Periods cleared. Select a new date range.")

with compare_tab:
    st.subheader("Compare athletes and periods")
    today = pd.Timestamp.now(tz="Pacific/Auckland").date()
    period_days = 84
    period_2 = (today - timedelta(days=period_days - 1), today)
    period_1 = (period_2[0] - timedelta(days=period_days), period_2[0] - timedelta(days=1))

    st.markdown(
        """
        <style>
        .st-key-compare_athlete_1 [data-baseweb="select"] *,
        .st-key-compare_period_1 input {
            color: #4FC3F7 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    with st.form("compare_form"):
        control_columns = st.columns(4)
        with control_columns[0]:
            compare_athlete_1 = st.selectbox(
                "Selection 1 athlete", available_athletes, index=0, key="compare_athlete_1"
            )
        with control_columns[1]:
            compare_athlete_2 = st.selectbox(
                "Selection 2 athlete", available_athletes, index=1, key="compare_athlete_2"
            )
        with control_columns[2]:
            compare_period_1 = st.date_input(
                "Selection 1 period", value=period_1, key="compare_period_1"
            )
        with control_columns[3]:
            compare_period_2 = st.date_input(
                "Selection 2 period", value=period_2, key="compare_period_2"
            )
        run_comparison = st.form_submit_button("Run comparison")

    if run_comparison:
        valid_periods = all(
            isinstance(period, (tuple, list))
            and len(period) == 2
            and period[0] <= period[1]
            for period in (compare_period_1, compare_period_2)
        )
        if valid_periods:
            st.session_state["compare_configuration"] = (
                compare_athlete_1,
                compare_athlete_2,
                tuple(compare_period_1),
                tuple(compare_period_2),
            )
        else:
            st.warning("Select a start and end date for both periods.")

    compare_configuration = st.session_state.get("compare_configuration")
    if compare_configuration is None:
        st.info("Choose two athlete-and-period combinations, then run the comparison.")
    else:
        compare_athlete_1, compare_athlete_2, period_1, period_2 = compare_configuration
        selections = [
            (compare_athlete_1, period_1),
            (compare_athlete_2, period_2),
        ]
        query_start = min(period[0] for _, period in selections)
        query_end = max(period[1] for _, period in selections)
        query_athletes = tuple(dict.fromkeys([compare_athlete_1, compare_athlete_2]))
        with st.spinner("Loading comparison data..."):
            compare_data = load_compare_data(query_athletes, query_start, query_end)

        if compare_data.empty:
            st.info("No data found for the selected athletes and periods.")
        else:
            selection_metrics = [
                build_compare_metrics(compare_data, athlete, [period])[0]
                for athlete, period in selections
            ]
            selection_labels = [
                f"Selection {index + 1}: {athlete} "
                f"({period[0]:%d %b %Y} - {period[1]:%d %b %Y})"
                for index, (athlete, period) in enumerate(selections)
            ]
            metric_tabs = st.tabs([
                "Training Time", "TSS", "Energy (kJ)", "Strength",
                "Power Zones", "Power Zones %",
            ])
            metric_names = [
                "Training Time", "TSS", "Energy (kJ)", "Strength",
                "Power Zones", "Power Zones %",
            ]

            for metric, metric_tab in zip(metric_names, metric_tabs):
                with metric_tab:
                    if metric in ("Power Zones", "Power Zones %"):
                        zone_values = [values[metric] for values in selection_metrics]
                        zones = sorted(set().union(*(values.index for values in zone_values)))
                        if not zones:
                            st.info("No power-zone data for these selections.")
                        else:
                            zone_chart = go.Figure()
                            for zone in zones:
                                zone_chart.add_trace(go.Bar(
                                    x=selection_labels,
                                    y=[values.get(zone, 0) for values in zone_values],
                                    name=str(zone),
                                ))
                            zone_chart.update_layout(
                                barmode="stack",
                                xaxis_title="Athlete and date range",
                                yaxis_title=(
                                    "Share of power-zone time (%)"
                                    if metric == "Power Zones %"
                                    else "Average power-zone time (minutes/week)"
                                ),
                                legend_title="Power zone",
                            )
                            st.plotly_chart(
                                zone_chart,
                                width="stretch",
                                key=f"compare_{metric}",
                            )
                    else:
                        weekly_selections = [
                            build_compare_weekly_metrics(
                                compare_data, athlete, period, metric
                            )
                            for athlete, period in selections
                        ]
                        week_count = max(len(values) for values in weekly_selections)
                        week_indices = range(week_count)
                        week_labels = [f"Week {index + 1}" for index in week_indices]
                        period_1_values = weekly_selections[0].reindex(week_indices)
                        period_2_values = weekly_selections[1].reindex(week_indices)
                        period_1_average = period_1_values.rolling(
                            window=4, min_periods=1
                        ).mean()
                        period_2_average = period_2_values.rolling(
                            window=4, min_periods=1
                        ).mean()
                        period_2_colors = [
                            "#FF6B6B" if second < first
                            else "#2ECC71" if second > first
                            else "#90A4AE"
                            for first, second in zip(period_1_values, period_2_values)
                        ]

                        metric_chart = go.Figure()
                        metric_chart.add_trace(go.Bar(
                            x=week_labels,
                            y=period_1_values,
                            name="Period 1",
                            showlegend=False,
                            marker_color="#4FC3F7",
                            hovertemplate=(
                                "%{x}<br>"
                                f"{selection_labels[0]}: %{{y:.1f}}<extra></extra>"
                            ),
                        ))
                        metric_chart.add_trace(go.Bar(
                            x=week_labels,
                            y=period_2_values,
                            name="Period 2",
                            showlegend=False,
                            marker_color=period_2_colors,
                            hovertemplate=(
                                "%{x}<br>"
                                f"{selection_labels[1]}: %{{y:.1f}}<extra></extra>"
                            ),
                        ))
                        metric_chart.add_trace(go.Scatter(
                            x=week_labels,
                            y=period_1_average,
                            name="Period 1 4-week average",
                            mode="lines+markers",
                            line=dict(color="#1565C0", width=3),
                            marker=dict(size=5),
                            hovertemplate=(
                                "%{x}<br>Period 1 4-week average: "
                                "%{y:.1f}<extra></extra>"
                            ),
                        ))
                        metric_chart.add_trace(go.Scatter(
                            x=week_labels,
                            y=period_2_average,
                            name="Period 2 4-week average",
                            mode="lines+markers",
                            line=dict(color="#FFD166", width=3),
                            marker=dict(size=5),
                            hovertemplate=(
                                "%{x}<br>Period 2 4-week average: "
                                "%{y:.1f}<extra></extra>"
                            ),
                        ))
                        metric_chart.update_layout(
                            barmode="group",
                            showlegend=True,
                            xaxis_title="Week of period",
                            yaxis_title=metric,
                        )
                        st.caption(
                            f"Blue: {selection_labels[0]} | Red/green: "
                            f"{selection_labels[1]} (red = lower, green = higher, "
                            "gray = equal to period 1)"
                        )
                        st.plotly_chart(
                            metric_chart,
                            width="stretch",
                            key=f"compare_{metric}",
                        )

            compare_summary_rows = []
            for metric in ("Training Time", "TSS", "Energy (kJ)"):
                first_value = selection_metrics[0][metric]
                second_value = selection_metrics[1][metric]
                percent_shift = (
                    (second_value - first_value) / abs(first_value) * 100
                    if first_value != 0
                    else np.nan
                )
                compare_summary_rows.append({
                    "Metric": metric,
                    "Selection 1": selection_labels[0],
                    "Selection 2": selection_labels[1],
                    "Selection 1 avg/week": first_value,
                    "Selection 2 avg/week": second_value,
                    "% shift (2 vs 1)": percent_shift,
                })
            st.subheader("Average weekly change")
            st.dataframe(
                pd.DataFrame(compare_summary_rows).style.format(
                    {
                        "Selection 1 avg/week": "{:.1f}",
                        "Selection 2 avg/week": "{:.1f}",
                        "% shift (2 vs 1)": "{:+.1f}%",
                    },
                    na_rep="n/a",
                ),
                hide_index=True,
            )

with athlete_tab:
    col1, col2, col3 = st.columns([3, 3, 2])
    with col1:
        selected_athlete = st.selectbox(
            "Select athlete", available_athletes, key="athlete_summary_selection"
        )
    with col2:
        weeks = st.slider(
            "Select number of past weeks", min_value=4, max_value=52,
            value=12, step=1, key="athlete_summary_weeks",
        )
    with col3:
        st.write("")
        bike_only = st.toggle("Bike only", value=False, key="athlete_bike_only")

    # ── Load athlete data ──────────────────────────────────────────────────────────
    # Safe defaults so tab code never hits NameError
    df_raw = pd.DataFrame()
    df_athlete_data_zones = pd.DataFrame()
    df_athlete_data_zones_restrict = pd.DataFrame()
    current_week_start = pd.Timestamp.now(tz='Pacific/Auckland').normalize().tz_localize(None)
    current_week_start = current_week_start - pd.Timedelta(days=current_week_start.weekday())

    if selected_athlete:
        try:
            with st.spinner("Loading data..."):
                df_raw = load_athlete_data(selected_athlete, weeks)
        except Exception as e:
            st.error(f"❌ Failed to load data: {e}")
            df_raw = pd.DataFrame()

        if not df_raw.empty and "POWER_ZONE_LABEL" in df_raw.columns:
            df_athlete_data_zones = (
                df_raw[df_raw["POWER_ZONE_LABEL"].notna()]
                .sort_values(["START_TIME", "POWER_ZONE_MINIMUM"], ascending=[False, True])
                .copy()
            )
        elif not df_raw.empty:
            st.warning("POWER_ZONE_LABEL column not found in the data.")

    # Add WEEK column - week starts on Monday, current week = 0
    if not df_raw.empty:
        # Define the start of the current week (Monday of this week)
        today = pd.Timestamp.now(tz='Pacific/Auckland').normalize().tz_localize(None)
        days_since_monday = today.weekday()  # Monday = 0, Sunday = 6
        current_week_start = today - pd.Timedelta(days=days_since_monday)

        def _weeks_past(ts):
            ts = pd.Timestamp(ts).normalize()
            return (current_week_start - (ts - pd.Timedelta(days=ts.weekday()))).days // 7

        df_raw['WEEKS_PAST'] = df_raw['START_TIME'].apply(_weeks_past)

        if not df_athlete_data_zones.empty:
            df_athlete_data_zones['WEEKS_PAST'] = df_athlete_data_zones['START_TIME'].apply(_weeks_past)

            # Reorder columns to put WEEKS_PAST in 7th position
            cols = df_athlete_data_zones.columns.tolist()
            if 'WEEKS_PAST' in cols:
                cols.remove('WEEKS_PAST')
                cols.insert(6, 'WEEKS_PAST')
                df_athlete_data_zones = df_athlete_data_zones[cols]
        
        # Filter to show only recent weeks (1 to weeks)
        recent_weeks = list(range(1, weeks + 1))

        df_raw_restrict = df_raw[df_raw['WEEKS_PAST'].isin(recent_weeks)].copy()

        df_athlete_data_zones_restrict = df_athlete_data_zones[
            df_athlete_data_zones['WEEKS_PAST'].isin(recent_weeks)
        ].copy() if not df_athlete_data_zones.empty else pd.DataFrame()

        # Strength data captured before bike-only filter so it's always shown regardless of toggle
        df_strength_restrict = df_raw_restrict[df_raw_restrict['WORKOUT_TYPE'] == 'Strength'].copy()

        # Apply bike-only filter if selected (MTB and Bike sessions only)
        if bike_only:
            _bike_types = ['MTB', 'Bike']
            df_raw = df_raw[df_raw['WORKOUT_TYPE'].isin(_bike_types)].copy()
            df_raw_restrict = df_raw_restrict[df_raw_restrict['WORKOUT_TYPE'].isin(_bike_types)].copy()
            if not df_athlete_data_zones.empty:
                df_athlete_data_zones = df_athlete_data_zones[df_athlete_data_zones['WORKOUT_TYPE'].isin(_bike_types)].copy()
            if not df_athlete_data_zones_restrict.empty:
                df_athlete_data_zones_restrict = df_athlete_data_zones_restrict[df_athlete_data_zones_restrict['WORKOUT_TYPE'].isin(_bike_types)].copy()
    else:
        df_raw_restrict = pd.DataFrame()

    hero_today = pd.Timestamp.now(tz="Pacific/Auckland").date()
    hero_periods = _athlete_hero_periods(hero_today)
    hero_history_start = min(
        period_name[0]
        for period in hero_periods
        for period_name in (period["current"], period["previous"], period["year_ago"])
    )
    hero_history = pd.DataFrame()
    if selected_athlete:
        try:
            with st.spinner("Loading history for period tiles..."):
                hero_history = load_compare_data(
                    (selected_athlete,), hero_history_start, hero_today
                )
        except Exception as error:
            st.warning(f"Could not load history for period tiles: {error}")

    # Create tabs for different chart types
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Training Time", "TSS", "Energy (kJ)", "Strength", "Power Zones", "Power Zones %"])

    # TAB 1: Weekly Training Time
    with tab1:
        render_athlete_hero_tiles(hero_history, "Training Time", bike_only, hero_today)
        if not df_raw_restrict.empty and 'DURATION_MINS' in df_raw_restrict.columns:
            
            # Sum DURATION_MINS across all activities — only populated on the workout-level row, not per-zone rows
            weekly_time = (
                df_raw_restrict
                .groupby('WEEKS_PAST')['DURATION_MINS'].sum().reset_index()
            )
            weekly_time['HOURS'] = (weekly_time['DURATION_MINS'] / 60).round(2)
            
            # Calculate the Monday date for each week
            weekly_time['WEEK_START_DATE'] = weekly_time['WEEKS_PAST'].apply(
                lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
            )
        
            # Sort by weeks_past for proper display
            weekly_time = weekly_time.sort_values('WEEKS_PAST')
        
        # Calculate rolling 4-week average from the original (unrestricted) data
        if not df_raw_restrict.empty and 'DURATION_MINS' in df_raw_restrict.columns and not df_raw.empty:
            # Sum DURATION_MINS across all activities — only populated on the workout-level row, not per-zone rows
            # Exclude WEEKS_PAST=0 (current partial week) so it doesn't skew rolling averages
            all_weekly_time = (
                df_raw[df_raw['WEEKS_PAST'] >= 1]
                .groupby('WEEKS_PAST')['DURATION_MINS'].sum().reset_index()
            )
            # Fill weeks with no activity as zero so rolling averages treat them as rest weeks
            _max_wp = int(df_raw[df_raw['WEEKS_PAST'] >= 1]['WEEKS_PAST'].max())
            all_weekly_time = (
                all_weekly_time.set_index('WEEKS_PAST')
                .reindex(range(1, _max_wp + 1), fill_value=0)
                .reset_index()
            )
            all_weekly_time['HOURS'] = (all_weekly_time['DURATION_MINS'] / 60).round(2)
            all_weekly_time = all_weekly_time.sort_values('WEEKS_PAST', ascending=False)
            
            # Calculate 4-week rolling average
            all_weekly_time['ROLLING_4WK_AVG'] = all_weekly_time['HOURS'].rolling(window=4, min_periods=1).mean().round(2)
            
            # Calculate 8-week centrally weighted rolling average
            def weighted_rolling_8week(series):
                """Calculate 8-week centrally weighted rolling average"""
                weights = [1, 2, 3, 4, 4, 3, 2, 1]  # Central weighting: 1st & 8th=1, 2nd & 7th=2, etc.
                result = []
                
                for i in range(len(series)):
                    if i < 7:  # Not enough data for full 8-week window
                        # Use available data with proportional weighting
                        available_data = series.iloc[:i+1]
                        available_weights = weights[-len(available_data):]
                        if len(available_data) > 0:
                            weighted_avg = (available_data * available_weights).sum() / sum(available_weights)
                            result.append(weighted_avg)
                        else:
                            result.append(np.nan)
                    else:
                        # Full 8-week window available
                        window_data = series.iloc[i-7:i+1]
                        weighted_avg = (window_data * weights).sum() / sum(weights)
                        result.append(weighted_avg)
                
                return pd.Series(result, index=series.index)
            
            all_weekly_time['ROLLING_8WK_WEIGHTED_AVG'] = weighted_rolling_8week(all_weekly_time['HOURS']).round(2)
            
            # Calculate 8-week log average (linearly increasing weights)
            def log_rolling_8week(series):
                """Calculate 8-week log rolling average with linearly increasing weights"""
                weights = [1, 2, 3, 4, 5, 6, 7, 8]  # Increasing weights: 1st week=1, 8th week=8
                result = []
                
                for i in range(len(series)):
                    if i < 7:  # Not enough data for full 8-week window
                        # Use available data with proportional weighting
                        available_data = series.iloc[:i+1]
                        available_weights = weights[:len(available_data)]
                        if len(available_data) > 0:
                            weighted_avg = (available_data * available_weights).sum() / sum(available_weights)
                            result.append(weighted_avg)
                        else:
                            result.append(np.nan)
                    else:
                        # Full 8-week window available
                        window_data = series.iloc[i-7:i+1]
                        weighted_avg = (window_data * weights).sum() / sum(weights)
                        result.append(weighted_avg)
                
                return pd.Series(result, index=series.index)
            
            all_weekly_time['ROLLING_8WK_LOG_AVG'] = log_rolling_8week(all_weekly_time['HOURS']).round(2)
            
            # HH:mm formatted columns for tooltips
            def _fmt_hhmm(h):
                if pd.isna(h):
                    return ''
                total_mins = round(h * 60)
                return f"{total_mins // 60}:{total_mins % 60:02d}"
            
            weekly_time['HOURS_HHMM'] = weekly_time['HOURS'].apply(_fmt_hhmm)
            all_weekly_time['HOURS_HHMM'] = all_weekly_time['HOURS'].apply(_fmt_hhmm)
            all_weekly_time['ROLLING_4WK_HHMM'] = all_weekly_time['ROLLING_4WK_AVG'].apply(_fmt_hhmm)
            all_weekly_time['ROLLING_8WK_WEIGHTED_HHMM'] = all_weekly_time['ROLLING_8WK_WEIGHTED_AVG'].apply(_fmt_hhmm)
            all_weekly_time['ROLLING_8WK_LOG_HHMM'] = all_weekly_time['ROLLING_8WK_LOG_AVG'].apply(_fmt_hhmm)

            # Weekly planned hours (TOTAL_TIME_PLANNED in seconds)
            weekly_time_planned = (
                df_raw_restrict.groupby('WEEKS_PAST')['TOTAL_TIME_PLANNED']
                .sum().reset_index()
            )
            weekly_time_planned['HOURS_PLANNED'] = (weekly_time_planned['TOTAL_TIME_PLANNED'] / 3_600_000).round(2)
            weekly_time_planned['HOURS_PLANNED_HHMM'] = weekly_time_planned['HOURS_PLANNED'].apply(_fmt_hhmm)
            weekly_time_planned['WEEK_START_DATE'] = weekly_time_planned['WEEKS_PAST'].apply(
                lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
            )
            weekly_time_planned = weekly_time_planned.sort_values('WEEKS_PAST')

            # Calculate week start dates for rolling average
            all_weekly_time['WEEK_START_DATE'] = all_weekly_time['WEEKS_PAST'].apply(
                lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
            )
            
            # Filter rolling average data to match the display range
            rolling_avg_display = all_weekly_time[
                all_weekly_time['WEEKS_PAST'].isin(weekly_time['WEEKS_PAST'])
            ].copy()
        
            # Create the combined chart using plotly graph objects for more control
            fig = go.Figure()
            
            # Add bar chart for weekly hours
            _sel_time_wp = st.session_state.get('sel_time_wp')
            _time_colors = ['#4FC3F7' if wp == _sel_time_wp else 'lightblue' for wp in weekly_time['WEEKS_PAST']]
            _time_borders = ['white' if wp == _sel_time_wp else 'rgba(0,0,0,0)' for wp in weekly_time['WEEKS_PAST']]
            fig.add_trace(go.Bar(
                x=weekly_time['WEEK_START_DATE'],
                y=weekly_time['HOURS'],
                name='Weekly Hours',
                marker_color=_time_colors,
                marker_line_color=_time_borders,
                marker_line_width=2,
                customdata=weekly_time['HOURS_HHMM'],
                hovertemplate='Hours: %{customdata}<extra></extra>',
                selected=dict(marker=dict(opacity=1)),
                unselected=dict(marker=dict(opacity=1)),
            ))

            # Planned hours bar
            fig.add_trace(go.Bar(
                x=weekly_time_planned['WEEK_START_DATE'],
                y=weekly_time_planned['HOURS_PLANNED'],
                name='Planned Hours',
                marker_color='rgba(79, 195, 247, 0.35)',
                marker_line_color='#4FC3F7',
                marker_line_width=2,
                customdata=weekly_time_planned['HOURS_PLANNED_HHMM'],
                hovertemplate='Planned: %{customdata}<extra></extra>',
            ))

            # Add rolling average lines if data exists
            if not df_raw.empty and len(rolling_avg_display) > 0:
                # 4-week rolling average
                fig.add_trace(go.Scatter(
                    x=rolling_avg_display['WEEK_START_DATE'],
                    y=rolling_avg_display['ROLLING_4WK_AVG'],
                    mode='lines+markers',
                    name='4-Week Rolling Average',
                    line=dict(color='red', width=3),
                    marker=dict(size=6),
                    customdata=rolling_avg_display['ROLLING_4WK_HHMM'],
                    hovertemplate='4-Week Avg: %{customdata}<extra></extra>'
                ))
                
                # 8-week centrally weighted rolling average
                fig.add_trace(go.Scatter(
                    x=rolling_avg_display['WEEK_START_DATE'],
                    y=rolling_avg_display['ROLLING_8WK_WEIGHTED_AVG'],
                    mode='lines+markers',
                    name='8-Week Weighted Average',
                    line=dict(color='green', width=3),
                    marker=dict(size=6),
                    customdata=rolling_avg_display['ROLLING_8WK_WEIGHTED_HHMM'],
                    hovertemplate='8-Week Weighted Avg: %{customdata}<extra></extra>'
                ))
                
                # 8-week log average
                fig.add_trace(go.Scatter(
                    x=rolling_avg_display['WEEK_START_DATE'],
                    y=rolling_avg_display['ROLLING_8WK_LOG_AVG'],
                    mode='lines+markers',
                    name='8-Week Log Average',
                    line=dict(color='purple', width=3),
                    marker=dict(size=6),
                    customdata=rolling_avg_display['ROLLING_8WK_LOG_HHMM'],
                    hovertemplate='8-Week Log Avg: %{customdata}<extra></extra>'
                ))
            
            # Update layout for better appearance
            fig.update_layout(
                # title=f'Last {weeks} weeks',
                title="Weekly Training Time with Rolling Averages",
                showlegend=True,
                hovermode='x unified',
                barmode='group',
            )
            
            # Format x-axis to show dates nicely
            fig.update_xaxes(tickformat="%Y-%m-%d")
            
            sel_time = st.plotly_chart(fig, on_select="rerun", key="chart_time", width='stretch')

            if sel_time.selection.points:
                _cx = sel_time.selection.points[0]["x"]
                _ct = pd.Timestamp(_cx).normalize()
                _cm = _ct - pd.Timedelta(days=_ct.weekday())
                _cwp = round((current_week_start - _cm).days / 7)
                if st.session_state.get('sel_time_wp') != _cwp:
                    st.session_state['sel_time_wp'] = _cwp
                    st.rerun()

            if st.session_state.get('sel_time_wp') is not None:
                sel_wp = st.session_state['sel_time_wp']
                sel_monday = current_week_start - pd.Timedelta(weeks=sel_wp)
                week_sessions = df_raw_restrict[
                    (df_raw_restrict['WEEKS_PAST'] == sel_wp) &
                    df_raw_restrict['DURATION_MINS'].notna()
                ].copy()
                if not week_sessions.empty:
                    week_sessions['Date'] = pd.to_datetime(week_sessions['START_TIME']).dt.date
                    week_sessions['Duration'] = week_sessions['DURATION_MINS'].apply(
                        lambda m: f"{int(m)//60}:{int(m)%60:02d}" if pd.notna(m) else ''
                    )
                    week_sessions['Planned Duration'] = week_sessions['TOTAL_TIME_PLANNED'].apply(
                        lambda s: f"{int(s)//3_600_000}:{int(s)%3_600_000//60_000:02d}" if pd.notna(s) and s > 0 else ''
                    )
                    week_sessions['TSS'] = week_sessions['TSS'].round(1)
                    week_sessions['Planned TSS'] = week_sessions['TSS_PLANNED'].apply(
                        lambda t: round(float(t), 1) if pd.notna(t) and float(t) > 0 else ''
                    )
                    week_sessions['Energy (kJ)'] = (week_sessions['ENERGY'] / 1000).round(1)
                    week_sessions['Planned Energy (kJ)'] = week_sessions['ENERGY_PLANNED'].apply(
                        lambda e: round(float(e) / 1000, 1) if pd.notna(e) and float(e) > 0 else ''
                    )
                    week_sessions['Description'] = week_sessions['DESCRIPTION'].fillna('').astype(str).str.replace(r'<br\s*/?>', ' ', regex=True).str.strip()
                    tbl = week_sessions[['WORKOUT_TYPE', 'Date', 'Duration', 'Planned Duration', 'TSS', 'Planned TSS', 'Energy (kJ)', 'Planned Energy (kJ)', 'Description']].rename(
                        columns={'WORKOUT_TYPE': 'Session'}
                    ).sort_values('Date').reset_index(drop=True)
                    st.markdown(f"**Sessions — w/c {sel_monday.strftime('%d %b %Y')}**")
                    st.dataframe(tbl, hide_index=True, use_container_width=True)
                else:
                    st.info(f"No sessions found for w/c {sel_monday.strftime('%d %b %Y')}.")
        else:
            st.info("No data available for the selected athlete and time period.")

    # TAB 2: Weekly TSS
    with tab2:
        render_athlete_hero_tiles(hero_history, "TSS", bike_only, hero_today)
        if not df_raw_restrict.empty and 'TSS' in df_raw_restrict.columns:
            
            # Group by weeks and sum the TSS for restricted data (all sessions, not just power-zone ones)
            weekly_tss = df_raw_restrict.groupby('WEEKS_PAST')['TSS'].sum().reset_index()
            weekly_tss['TSS'] = weekly_tss['TSS'].round(1)
            
            # Calculate the Monday date for each week
            weekly_tss['WEEK_START_DATE'] = weekly_tss['WEEKS_PAST'].apply(
                lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
            )
            
            # Sort by weeks_past for proper display
            weekly_tss = weekly_tss.sort_values('WEEKS_PAST')

            # Weekly planned TSS
            weekly_tss_planned = (
                df_raw_restrict.groupby('WEEKS_PAST')['TSS_PLANNED']
                .sum().reset_index()
            )
            weekly_tss_planned['TSS_PLANNED'] = weekly_tss_planned['TSS_PLANNED'].round(1)
            weekly_tss_planned['WEEK_START_DATE'] = weekly_tss_planned['WEEKS_PAST'].apply(
                lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
            )
            weekly_tss_planned = weekly_tss_planned.sort_values('WEEKS_PAST')

            # Calculate rolling averages from the full unrestricted raw data
            if not df_raw.empty:
                # Group all data by weeks and sum the TSS
                # Exclude WEEKS_PAST=0 (current partial week) so it doesn't skew rolling averages
                all_weekly_tss = (
                    df_raw[df_raw['WEEKS_PAST'] >= 1]
                    .groupby('WEEKS_PAST')['TSS'].sum().reset_index()
                )
                # Fill weeks with no activity as zero so rolling averages treat them as rest weeks
                _max_wp_tss = int(df_raw[df_raw['WEEKS_PAST'] >= 1]['WEEKS_PAST'].max())
                all_weekly_tss = (
                    all_weekly_tss.set_index('WEEKS_PAST')
                    .reindex(range(1, _max_wp_tss + 1), fill_value=0)
                    .reset_index()
                )
                all_weekly_tss['TSS'] = all_weekly_tss['TSS'].round(1)
                all_weekly_tss = all_weekly_tss.sort_values('WEEKS_PAST', ascending=False)
                
                # Calculate rolling averages
                all_weekly_tss['ROLLING_4WK_AVG'] = all_weekly_tss['TSS'].rolling(window=4, min_periods=1).mean().round(1)
                
                # 8-week centrally weighted average
                def weighted_rolling_8week_tss(series):
                    weights = [1, 2, 3, 4, 4, 3, 2, 1]
                    result = []
                    for i in range(len(series)):
                        if i < 7:
                            available_data = series.iloc[:i+1]
                            available_weights = weights[-len(available_data):]
                            if len(available_data) > 0:
                                weighted_avg = (available_data * available_weights).sum() / sum(available_weights)
                                result.append(weighted_avg)
                            else:
                                result.append(np.nan)
                        else:
                            window_data = series.iloc[i-7:i+1]
                            weighted_avg = (window_data * weights).sum() / sum(weights)
                            result.append(weighted_avg)
                    return pd.Series(result, index=series.index)
                
                # 8-week log average
                def log_rolling_8week_tss(series):
                    weights = [1, 2, 3, 4, 5, 6, 7, 8]
                    result = []
                    for i in range(len(series)):
                        if i < 7:
                            available_data = series.iloc[:i+1]
                            available_weights = weights[:len(available_data)]
                            if len(available_data) > 0:
                                weighted_avg = (available_data * available_weights).sum() / sum(available_weights)
                                result.append(weighted_avg)
                            else:
                                result.append(np.nan)
                        else:
                            window_data = series.iloc[i-7:i+1]
                            weighted_avg = (window_data * weights).sum() / sum(weights)
                            result.append(weighted_avg)
                    return pd.Series(result, index=series.index)
                
                all_weekly_tss['ROLLING_8WK_WEIGHTED_AVG'] = weighted_rolling_8week_tss(all_weekly_tss['TSS']).round(1)
                all_weekly_tss['ROLLING_8WK_LOG_AVG'] = log_rolling_8week_tss(all_weekly_tss['TSS']).round(1)
                
                # Calculate week start dates for rolling average
                all_weekly_tss['WEEK_START_DATE'] = all_weekly_tss['WEEKS_PAST'].apply(
                    lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
                )
                
                # Filter rolling average data to match the display range
                rolling_avg_tss_display = all_weekly_tss[
                    all_weekly_tss['WEEKS_PAST'].isin(weekly_tss['WEEKS_PAST'])
                ].copy()
            
            # Create TSS chart
            fig_tss = go.Figure()
            
            # Add bar chart for weekly TSS
            _sel_tss_wp = st.session_state.get('sel_tss_wp')
            _tss_colors = ['#FF6B6B' if wp == _sel_tss_wp else 'lightcoral' for wp in weekly_tss['WEEKS_PAST']]
            _tss_borders = ['white' if wp == _sel_tss_wp else 'rgba(0,0,0,0)' for wp in weekly_tss['WEEKS_PAST']]
            fig_tss.add_trace(go.Bar(
                x=weekly_tss['WEEK_START_DATE'],
                y=weekly_tss['TSS'],
                name='Weekly TSS',
                marker_color=_tss_colors,
                marker_line_color=_tss_borders,
                marker_line_width=2,
                hovertemplate='TSS: %{y}<extra></extra>',
                selected=dict(marker=dict(opacity=1)),
                unselected=dict(marker=dict(opacity=1)),
            ))

            # Planned TSS bar
            fig_tss.add_trace(go.Bar(
                x=weekly_tss_planned['WEEK_START_DATE'],
                y=weekly_tss_planned['TSS_PLANNED'],
                name='Planned TSS',
                marker_color='rgba(255, 107, 107, 0.35)',
                marker_line_color='#FF6B6B',
                marker_line_width=2,
                hovertemplate='Planned TSS: %{y}<extra></extra>',
            ))

            # Add rolling average lines if data exists
            if not df_raw.empty and len(rolling_avg_tss_display) > 0:
                fig_tss.add_trace(go.Scatter(
                    x=rolling_avg_tss_display['WEEK_START_DATE'],
                    y=rolling_avg_tss_display['ROLLING_4WK_AVG'],
                    mode='lines+markers',
                    name='4-Week Rolling Average',
                    line=dict(color='red', width=3),
                    marker=dict(size=6),
                    hovertemplate='4-Week Avg: %{y} TSS<extra></extra>'
                ))
                
                fig_tss.add_trace(go.Scatter(
                    x=rolling_avg_tss_display['WEEK_START_DATE'],
                    y=rolling_avg_tss_display['ROLLING_8WK_WEIGHTED_AVG'],
                    mode='lines+markers',
                    name='8-Week Weighted Average',
                    line=dict(color='green', width=3),
                    marker=dict(size=6),
                    hovertemplate='8-Week Weighted Avg: %{y} TSS<extra></extra>'
                ))
                
                fig_tss.add_trace(go.Scatter(
                    x=rolling_avg_tss_display['WEEK_START_DATE'],
                    y=rolling_avg_tss_display['ROLLING_8WK_LOG_AVG'],
                    mode='lines+markers',
                    name='8-Week Log Average',
                    line=dict(color='purple', width=3),
                    marker=dict(size=6),
                    hovertemplate='8-Week Log Avg: %{y} TSS<extra></extra>'
                ))
            
            fig_tss.update_layout(
                # title=f'Last {weeks} weeks',
                title="Weekly TSS with Rolling Averages",
                showlegend=True,
                hovermode='x unified',
                barmode='group',
            )
            
            fig_tss.update_xaxes(tickformat="%Y-%m-%d")
            sel_tss = st.plotly_chart(fig_tss, on_select="rerun", key="chart_tss", width='stretch')

            if sel_tss.selection.points:
                _cx = sel_tss.selection.points[0]["x"]
                _ct = pd.Timestamp(_cx).normalize()
                _cm = _ct - pd.Timedelta(days=_ct.weekday())
                _cwp = round((current_week_start - _cm).days / 7)
                if st.session_state.get('sel_tss_wp') != _cwp:
                    st.session_state['sel_tss_wp'] = _cwp
                    st.rerun()

            if st.session_state.get('sel_tss_wp') is not None:
                sel_wp = st.session_state['sel_tss_wp']
                sel_monday = current_week_start - pd.Timedelta(weeks=sel_wp)
                week_sessions = df_raw_restrict[
                    (df_raw_restrict['WEEKS_PAST'] == sel_wp) &
                    df_raw_restrict['DURATION_MINS'].notna()
                ].copy()
                if not week_sessions.empty:
                    week_sessions['Date'] = pd.to_datetime(week_sessions['START_TIME']).dt.date
                    week_sessions['Duration'] = week_sessions['DURATION_MINS'].apply(
                        lambda m: f"{int(m)//60}:{int(m)%60:02d}" if pd.notna(m) else ''
                    )
                    week_sessions['Planned Duration'] = week_sessions['TOTAL_TIME_PLANNED'].apply(
                        lambda s: f"{int(s)//3_600_000}:{int(s)%3_600_000//60_000:02d}" if pd.notna(s) and s > 0 else ''
                    )
                    week_sessions['TSS'] = week_sessions['TSS'].round(1)
                    week_sessions['Planned TSS'] = week_sessions['TSS_PLANNED'].apply(
                        lambda t: round(float(t), 1) if pd.notna(t) and float(t) > 0 else ''
                    )
                    week_sessions['Energy (kJ)'] = (week_sessions['ENERGY'] / 1000).round(1)
                    week_sessions['Planned Energy (kJ)'] = week_sessions['ENERGY_PLANNED'].apply(
                        lambda e: round(float(e) / 1000, 1) if pd.notna(e) and float(e) > 0 else ''
                    )
                    week_sessions['Description'] = week_sessions['DESCRIPTION'].fillna('').astype(str).str.replace(r'<br\s*/?>', ' ', regex=True).str.strip()
                    tbl = week_sessions[['WORKOUT_TYPE', 'Date', 'Duration', 'Planned Duration', 'TSS', 'Planned TSS', 'Energy (kJ)', 'Planned Energy (kJ)', 'Description']].rename(
                        columns={'WORKOUT_TYPE': 'Session'}
                    ).sort_values('Date').reset_index(drop=True)
                    st.markdown(f"**Sessions — w/c {sel_monday.strftime('%d %b %Y')}**")
                    st.dataframe(tbl, hide_index=True, use_container_width=True)
                else:
                    st.info(f"No sessions found for w/c {sel_monday.strftime('%d %b %Y')}.")
        else:
            st.info("No data available for the selected athlete and time period.")

    # TAB 3: Weekly Energy
    with tab3:
        render_athlete_hero_tiles(hero_history, "Energy (kJ)", bike_only, hero_today)
        if not df_athlete_data_zones_restrict.empty and 'ENERGY' in df_athlete_data_zones_restrict.columns:
            
            # Group by weeks and sum the ENERGY for restricted data
            weekly_energy = df_athlete_data_zones_restrict.groupby('WEEKS_PAST')['ENERGY'].sum().reset_index()
            weekly_energy['ENERGY_KJ'] = (weekly_energy['ENERGY'] / 1000).round(1)  # Convert to kJ
        
            # Calculate the Monday date for each week
            weekly_energy['WEEK_START_DATE'] = weekly_energy['WEEKS_PAST'].apply(
                lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
            )
            
            # Sort by weeks_past for proper display
            weekly_energy = weekly_energy.sort_values('WEEKS_PAST')

            # Weekly planned energy (ENERGY_PLANNED is session-level, aggregate from df_raw_restrict)
            weekly_energy_planned = (
                df_raw_restrict.groupby('WEEKS_PAST')['ENERGY_PLANNED']
                .sum().reset_index()
            )
            weekly_energy_planned['ENERGY_PLANNED_KJ'] = (weekly_energy_planned['ENERGY_PLANNED'] / 1000).round(1)
            weekly_energy_planned['WEEK_START_DATE'] = weekly_energy_planned['WEEKS_PAST'].apply(
                lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
            )
            weekly_energy_planned = weekly_energy_planned.sort_values('WEEKS_PAST')

            # Calculate rolling averages from the original (unrestricted) data
            if not df_athlete_data_zones.empty:
                # Group all data by weeks and sum the ENERGY (exclude partial current week)
                all_weekly_energy = (
                    df_athlete_data_zones[df_athlete_data_zones['WEEKS_PAST'] >= 1]
                    .groupby('WEEKS_PAST')['ENERGY'].sum().reset_index()
                )
                # Fill weeks with no activity as zero so rolling averages treat them as rest weeks
                _max_wp_energy = int(df_athlete_data_zones[df_athlete_data_zones['WEEKS_PAST'] >= 1]['WEEKS_PAST'].max())
                all_weekly_energy = (
                    all_weekly_energy.set_index('WEEKS_PAST')
                    .reindex(range(1, _max_wp_energy + 1), fill_value=0)
                    .reset_index()
                )
                all_weekly_energy['ENERGY_KJ'] = (all_weekly_energy['ENERGY'] / 1000).round(1)
                all_weekly_energy = all_weekly_energy.sort_values('WEEKS_PAST', ascending=False)
                
                # Calculate rolling averages
                all_weekly_energy['ROLLING_4WK_AVG'] = all_weekly_energy['ENERGY_KJ'].rolling(window=4, min_periods=1).mean().round(1)
                
                # 8-week centrally weighted average
                def weighted_rolling_8week_energy(series):
                    weights = [1, 2, 3, 4, 4, 3, 2, 1]
                    result = []
                    for i in range(len(series)):
                        if i < 7:
                            available_data = series.iloc[:i+1]
                            available_weights = weights[-len(available_data):]
                            if len(available_data) > 0:
                                weighted_avg = (available_data * available_weights).sum() / sum(available_weights)
                                result.append(weighted_avg)
                            else:
                                result.append(np.nan)
                        else:
                            window_data = series.iloc[i-7:i+1]
                            weighted_avg = (window_data * weights).sum() / sum(weights)
                            result.append(weighted_avg)
                    return pd.Series(result, index=series.index)
                
                # 8-week log average
                def log_rolling_8week_energy(series):
                    weights = [1, 2, 3, 4, 5, 6, 7, 8]
                    result = []
                    for i in range(len(series)):
                        if i < 7:
                            available_data = series.iloc[:i+1]
                            available_weights = weights[:len(available_data)]
                            if len(available_data) > 0:
                                weighted_avg = (available_data * available_weights).sum() / sum(available_weights)
                                result.append(weighted_avg)
                            else:
                                result.append(np.nan)
                        else:
                            window_data = series.iloc[i-7:i+1]
                            weighted_avg = (window_data * weights).sum() / sum(weights)
                            result.append(weighted_avg)
                    return pd.Series(result, index=series.index)
                
                all_weekly_energy['ROLLING_8WK_WEIGHTED_AVG'] = weighted_rolling_8week_energy(all_weekly_energy['ENERGY_KJ']).round(1)
                all_weekly_energy['ROLLING_8WK_LOG_AVG'] = log_rolling_8week_energy(all_weekly_energy['ENERGY_KJ']).round(1)
                
                # Calculate week start dates for rolling average
                all_weekly_energy['WEEK_START_DATE'] = all_weekly_energy['WEEKS_PAST'].apply(
                    lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
                )
                
                # Filter rolling average data to match the display range
                rolling_avg_energy_display = all_weekly_energy[
                    all_weekly_energy['WEEKS_PAST'].isin(weekly_energy['WEEKS_PAST'])
                ].copy()
            
            # Create Energy chart
            fig_energy = go.Figure()
            
            # Add bar chart for weekly energy
            _sel_energy_wp = st.session_state.get('sel_energy_wp')
            _energy_colors = ['#66FF99' if wp == _sel_energy_wp else 'lightgreen' for wp in weekly_energy['WEEKS_PAST']]
            _energy_borders = ['white' if wp == _sel_energy_wp else 'rgba(0,0,0,0)' for wp in weekly_energy['WEEKS_PAST']]
            fig_energy.add_trace(go.Bar(
                x=weekly_energy['WEEK_START_DATE'],
                y=weekly_energy['ENERGY_KJ'],
                name='Weekly Energy (kJ)',
                marker_color=_energy_colors,
                marker_line_color=_energy_borders,
                marker_line_width=2,
                hovertemplate='Energy: %{y} kJ<extra></extra>',
                selected=dict(marker=dict(opacity=1)),
                unselected=dict(marker=dict(opacity=1)),
            ))

            # Planned energy bar
            fig_energy.add_trace(go.Bar(
                x=weekly_energy_planned['WEEK_START_DATE'],
                y=weekly_energy_planned['ENERGY_PLANNED_KJ'],
                name='Planned Energy (kJ)',
                marker_color='rgba(102, 255, 153, 0.35)',
                marker_line_color='#66FF99',
                marker_line_width=2,
                hovertemplate='Planned Energy: %{y} kJ<extra></extra>',
            ))

            # Add rolling average lines if data exists
            if not df_athlete_data_zones.empty and len(rolling_avg_energy_display) > 0:
                fig_energy.add_trace(go.Scatter(
                    x=rolling_avg_energy_display['WEEK_START_DATE'],
                    y=rolling_avg_energy_display['ROLLING_4WK_AVG'],
                    mode='lines+markers',
                    name='4-Week Rolling Average',
                    line=dict(color='red', width=3),
                    marker=dict(size=6),
                    hovertemplate='4-Week Avg: %{y} kJ<extra></extra>'
                ))
                
                fig_energy.add_trace(go.Scatter(
                    x=rolling_avg_energy_display['WEEK_START_DATE'],
                    y=rolling_avg_energy_display['ROLLING_8WK_WEIGHTED_AVG'],
                    mode='lines+markers',
                    name='8-Week Weighted Average',
                    line=dict(color='green', width=3),
                    marker=dict(size=6),
                    hovertemplate='8-Week Weighted Avg: %{y} kJ<extra></extra>'
                ))
                
                fig_energy.add_trace(go.Scatter(
                    x=rolling_avg_energy_display['WEEK_START_DATE'],
                    y=rolling_avg_energy_display['ROLLING_8WK_LOG_AVG'],
                    mode='lines+markers',
                    name='8-Week Log Average',
                    line=dict(color='purple', width=3),
                    marker=dict(size=6),
                    hovertemplate='8-Week Log Avg: %{y} kJ<extra></extra>'
                ))
            
            fig_energy.update_layout(
                # title=f'Last {weeks} weeks',
                title="Weekly Energy (kJ) with Rolling Averages",
                showlegend=True,
                hovermode='x unified',
                barmode='group',
            )
            
            fig_energy.update_xaxes(tickformat="%Y-%m-%d")
            sel_energy = st.plotly_chart(fig_energy, on_select="rerun", key="chart_energy", width='stretch')

            if sel_energy.selection.points:
                _cx = sel_energy.selection.points[0]["x"]
                _ct = pd.Timestamp(_cx).normalize()
                _cm = _ct - pd.Timedelta(days=_ct.weekday())
                _cwp = round((current_week_start - _cm).days / 7)
                if st.session_state.get('sel_energy_wp') != _cwp:
                    st.session_state['sel_energy_wp'] = _cwp
                    st.rerun()

            if st.session_state.get('sel_energy_wp') is not None:
                sel_wp = st.session_state['sel_energy_wp']
                sel_monday = current_week_start - pd.Timedelta(weeks=sel_wp)
                week_sessions = df_raw_restrict[
                    (df_raw_restrict['WEEKS_PAST'] == sel_wp) &
                    df_raw_restrict['DURATION_MINS'].notna()
                ].copy()
                if not week_sessions.empty:
                    week_sessions['Date'] = pd.to_datetime(week_sessions['START_TIME']).dt.date
                    week_sessions['Duration'] = week_sessions['DURATION_MINS'].apply(
                        lambda m: f"{int(m)//60}:{int(m)%60:02d}" if pd.notna(m) else ''
                    )
                    week_sessions['Planned Duration'] = week_sessions['TOTAL_TIME_PLANNED'].apply(
                        lambda s: f"{int(s)//3_600_000}:{int(s)%3_600_000//60_000:02d}" if pd.notna(s) and s > 0 else ''
                    )
                    week_sessions['TSS'] = week_sessions['TSS'].round(1)
                    week_sessions['Planned TSS'] = week_sessions['TSS_PLANNED'].apply(
                        lambda t: round(float(t), 1) if pd.notna(t) and float(t) > 0 else ''
                    )
                    week_sessions['Energy (kJ)'] = (week_sessions['ENERGY'] / 1000).round(1)
                    week_sessions['Planned Energy (kJ)'] = week_sessions['ENERGY_PLANNED'].apply(
                        lambda e: round(float(e) / 1000, 1) if pd.notna(e) and float(e) > 0 else ''
                    )
                    week_sessions['Description'] = week_sessions['DESCRIPTION'].fillna('').astype(str).str.replace(r'<br\s*/?>', ' ', regex=True).str.strip()
                    tbl = week_sessions[['WORKOUT_TYPE', 'Date', 'Duration', 'Planned Duration', 'TSS', 'Planned TSS', 'Energy (kJ)', 'Planned Energy (kJ)', 'Description']].rename(
                        columns={'WORKOUT_TYPE': 'Session'}
                    ).sort_values('Date').reset_index(drop=True)
                    st.markdown(f"**Sessions — w/c {sel_monday.strftime('%d %b %Y')}**")
                    st.dataframe(tbl, hide_index=True, use_container_width=True)
                else:
                    st.info(f"No sessions found for w/c {sel_monday.strftime('%d %b %Y')}.")
        else:
            st.info("No data available for the selected athlete and time period.")

    # TAB 4: Strength Duration
    with tab4:
        if not df_strength_restrict.empty and 'DURATION_MINS' in df_strength_restrict.columns:
            # Sum actual duration per week
            weekly_strength = (
                df_strength_restrict
                .groupby('WEEKS_PAST')['DURATION_MINS'].sum().reset_index()
            )
            weekly_strength['HOURS'] = (weekly_strength['DURATION_MINS'] / 60).round(2)
            weekly_strength['WEEK_START_DATE'] = weekly_strength['WEEKS_PAST'].apply(
                lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
            )
            weekly_strength['HOURS_HHMM'] = weekly_strength['HOURS'].apply(
                lambda h: f"{round(h*60)//60}:{round(h*60)%60:02d}" if pd.notna(h) else ''
            )
            weekly_strength = weekly_strength.sort_values('WEEKS_PAST')

            # Sum planned duration per week (TOTAL_TIME_PLANNED in ms)
            weekly_strength_planned = (
                df_strength_restrict.groupby('WEEKS_PAST')['TOTAL_TIME_PLANNED']
                .sum().reset_index()
            )
            weekly_strength_planned['HOURS_PLANNED'] = (weekly_strength_planned['TOTAL_TIME_PLANNED'] / 3_600_000).round(2)
            weekly_strength_planned['HOURS_PLANNED_HHMM'] = weekly_strength_planned['HOURS_PLANNED'].apply(
                lambda h: f"{round(h*60)//60}:{round(h*60)%60:02d}" if pd.notna(h) else ''
            )
            weekly_strength_planned['WEEK_START_DATE'] = weekly_strength_planned['WEEKS_PAST'].apply(
                lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
            )
            weekly_strength_planned = weekly_strength_planned.sort_values('WEEKS_PAST')

            fig_strength = go.Figure()

            _sel_strength_wp = st.session_state.get('sel_strength_wp')
            _strength_colors = ['#FFA07A' if wp == _sel_strength_wp else 'lightsalmon' for wp in weekly_strength['WEEKS_PAST']]
            _strength_borders = ['white' if wp == _sel_strength_wp else 'rgba(0,0,0,0)' for wp in weekly_strength['WEEKS_PAST']]
            fig_strength.add_trace(go.Bar(
                x=weekly_strength['WEEK_START_DATE'],
                y=weekly_strength['HOURS'],
                name='Actual Duration',
                marker_color=_strength_colors,
                marker_line_color=_strength_borders,
                marker_line_width=2,
                customdata=weekly_strength['HOURS_HHMM'],
                hovertemplate='Duration: %{customdata}<extra></extra>',
                selected=dict(marker=dict(opacity=1)),
                unselected=dict(marker=dict(opacity=1)),
            ))

            fig_strength.add_trace(go.Bar(
                x=weekly_strength_planned['WEEK_START_DATE'],
                y=weekly_strength_planned['HOURS_PLANNED'],
                name='Planned Duration',
                marker_color='rgba(255, 160, 122, 0.35)',
                marker_line_color='#FFA07A',
                marker_line_width=2,
                customdata=weekly_strength_planned['HOURS_PLANNED_HHMM'],
                hovertemplate='Planned: %{customdata}<extra></extra>',
            ))

            fig_strength.update_layout(
                title="Weekly Strength Duration",
                showlegend=True,
                hovermode='x unified',
                barmode='group',
            )
            fig_strength.update_xaxes(tickformat="%Y-%m-%d")

            sel_strength = st.plotly_chart(fig_strength, on_select="rerun", key="chart_strength", width='stretch')

            if sel_strength.selection.points:
                _cx = sel_strength.selection.points[0]["x"]
                _ct = pd.Timestamp(_cx).normalize()
                _cm = _ct - pd.Timedelta(days=_ct.weekday())
                _cwp = round((current_week_start - _cm).days / 7)
                if st.session_state.get('sel_strength_wp') != _cwp:
                    st.session_state['sel_strength_wp'] = _cwp
                    st.rerun()

            if st.session_state.get('sel_strength_wp') is not None:
                sel_wp = st.session_state['sel_strength_wp']
                sel_monday = current_week_start - pd.Timedelta(weeks=sel_wp)
                week_sessions = df_strength_restrict[
                    (df_strength_restrict['WEEKS_PAST'] == sel_wp) &
                    df_strength_restrict['DURATION_MINS'].notna()
                ].copy()
                if not week_sessions.empty:
                    week_sessions['Date'] = pd.to_datetime(week_sessions['START_TIME']).dt.date
                    week_sessions['Duration'] = week_sessions['DURATION_MINS'].apply(
                        lambda m: f"{int(m)//60}:{int(m)%60:02d}" if pd.notna(m) else ''
                    )
                    week_sessions['Planned Duration'] = week_sessions['TOTAL_TIME_PLANNED'].apply(
                        lambda s: f"{int(s)//3_600_000}:{int(s)%3_600_000//60_000:02d}" if pd.notna(s) and s > 0 else ''
                    )
                    week_sessions['TSS'] = week_sessions['TSS'].round(1)
                    week_sessions['Description'] = week_sessions['DESCRIPTION'].fillna('').astype(str).str.replace(r'<br\s*/?>', ' ', regex=True).str.strip()
                    tbl = week_sessions[['Date', 'Duration', 'Planned Duration', 'TSS', 'Description']].sort_values('Date').reset_index(drop=True)
                    st.markdown(f"**Strength sessions \u2014 w/c {sel_monday.strftime('%d %b %Y')}**")
                    st.dataframe(tbl, hide_index=True, use_container_width=True)
                else:
                    st.info(f"No strength sessions found for w/c {sel_monday.strftime('%d %b %Y')}.")
        else:
            st.info("No strength data available for the selected athlete and time period.")

    # TAB 5: Power Zone Distribution (Raw)
    with tab5:
        st.subheader("Power Zone Distribution")
        
        if not df_athlete_data_zones_restrict.empty:
            # Check if we have the required columns
            if 'POWER_ZONE_LABEL' in df_athlete_data_zones_restrict.columns and 'POWER_ZONE_SECONDS' in df_athlete_data_zones_restrict.columns:
                # Convert seconds to minutes for better readability
                df_zones_copy = df_athlete_data_zones_restrict.copy()
                df_zones_copy['Power Zone Minutes'] = (df_zones_copy['POWER_ZONE_SECONDS'] / 60).round(2)
            
            # Group by Power Zone Label and sum the minutes
            zone_summary = df_zones_copy.groupby('POWER_ZONE_LABEL')['Power Zone Minutes'].sum().reset_index()
            zone_summary = zone_summary.sort_values('Power Zone Minutes', ascending=False)
            zone_summary['Power Zone Minutes'] = zone_summary['Power Zone Minutes'].round(2)
            
            # Show weekly breakdown using START_TIME column
            if 'START_TIME' in df_athlete_data_zones_restrict.columns:
                # Calculate week start date (Monday) for each date using WEEKS_PAST
                df_zones_copy['Week_Start'] = df_zones_copy['WEEKS_PAST'].apply(
                    lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
                )
                
                # Group by week start and power zone
                weekly_zones = df_zones_copy.groupby(['Week_Start', 'POWER_ZONE_LABEL'])['Power Zone Minutes'].sum().reset_index()
                weekly_zones['Power Zone Minutes'] = weekly_zones['Power Zone Minutes'].round(2)
                
                # Create mapping from Power Zone Label to power ranges (without decimal points)
                zone_mapping = df_zones_copy.groupby('POWER_ZONE_LABEL').agg({
                    'POWER_ZONE_MINIMUM': 'first',
                    'POWER_ZONE_MAXIMUM': 'first'
                }).reset_index()
                
                # Filter out zones with invalid power ranges
                valid_zones = zone_mapping[zone_mapping['POWER_ZONE_MINIMUM'].notna() & zone_mapping['POWER_ZONE_MAXIMUM'].notna()]['POWER_ZONE_LABEL'].tolist()
                weekly_zones = weekly_zones[weekly_zones['POWER_ZONE_LABEL'].isin(valid_zones)]
                zone_mapping = zone_mapping[zone_mapping['POWER_ZONE_LABEL'].isin(valid_zones)]
                
                # Handle NaN values before converting to int
                zone_mapping['Power Range'] = zone_mapping.apply(
                    lambda row: f"{int(row['POWER_ZONE_MINIMUM'])}-{int(row['POWER_ZONE_MAXIMUM'])}W" 
                    if pd.notna(row['POWER_ZONE_MINIMUM']) and pd.notna(row['POWER_ZONE_MAXIMUM']) 
                    else row['POWER_ZONE_LABEL'], 
                    axis=1
                )
                zone_map_dict = dict(zip(zone_mapping['POWER_ZONE_LABEL'], zone_mapping['Power Range']))
                
                # Pivot to get zones as columns
                weekly_pivot = weekly_zones.pivot(index='Week_Start', columns='POWER_ZONE_LABEL', values='Power Zone Minutes').fillna(0)
                
                # Sort columns by Power Zone Minimum to get lowest zones at bottom
                zone_order = zone_mapping.sort_values('POWER_ZONE_MINIMUM')['POWER_ZONE_LABEL'].tolist()
                weekly_pivot = weekly_pivot.reindex(columns=[col for col in zone_order if col in weekly_pivot.columns])
                
                # Create stacked bar chart for weekly view
                fig_weekly = go.Figure()
                
                colors = ["#485E89", "#4B8C67", "#24755B", '#B0D581', '#46BFB7', '#D2F2F9', '#9DE2F1', "#15C7EF"]
                
                for i, zone in enumerate(weekly_pivot.columns):
                    power_range = zone_map_dict.get(zone, zone)  # Use power range if available, otherwise fall back to zone label
                    fig_weekly.add_trace(go.Bar(
                        x=weekly_pivot.index,
                        y=weekly_pivot[zone],
                        name=power_range,
                        marker_color=colors[i % len(colors)],
                        hovertemplate="<b>Week Starting:</b> %{x}<br>" +
                                    f"<b>Power Zone:</b> {power_range}<br>" +
                                    "<b>Time:</b> %{y:.2f} minutes<br>" +
                                    "<extra></extra>"
                    ))
                
                fig_weekly.update_layout(
                    # title=f'Weekly Power Zone Distribution for {selected_athlete}',
                    xaxis_title='Week Starting (Monday)',
                    yaxis_title='Time (minutes)',
                    barmode='stack',
                    xaxis={'tickangle': 45}
                )
                
                st.plotly_chart(fig_weekly, width='stretch')

    # TAB 6: Power Zone Distribution (Percentage)
    with tab6:
        st.subheader("Power Zone Distribution (%)")
        
        if not df_athlete_data_zones_restrict.empty and 'POWER_ZONE_LABEL' in df_athlete_data_zones_restrict.columns and 'POWER_ZONE_SECONDS' in df_athlete_data_zones_restrict.columns:
            # Convert seconds to minutes for better readability
            df_zones_copy = df_athlete_data_zones_restrict.copy()
            df_zones_copy['Power Zone Minutes'] = (df_zones_copy['POWER_ZONE_SECONDS'] / 60).round(2)
            
            # Show weekly breakdown using START_TIME column
            if 'START_TIME' in df_athlete_data_zones_restrict.columns:
                # Calculate week start date (Monday) for each date using WEEKS_PAST
                df_zones_copy['Week_Start'] = df_zones_copy['WEEKS_PAST'].apply(
                    lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
                )
                
                # Group by week start and power zone
                weekly_zones = df_zones_copy.groupby(['Week_Start', 'POWER_ZONE_LABEL'])['Power Zone Minutes'].sum().reset_index()
                weekly_zones['Power Zone Minutes'] = weekly_zones['Power Zone Minutes'].round(2)
                
                # Create mapping from Power Zone Label to power ranges (without decimal points)
                zone_mapping = df_zones_copy.groupby('POWER_ZONE_LABEL').agg({
                    'POWER_ZONE_MINIMUM': 'first',
                    'POWER_ZONE_MAXIMUM': 'first'
                }).reset_index()
                
                # Filter out zones with invalid power ranges
                valid_zones = zone_mapping[zone_mapping['POWER_ZONE_MINIMUM'].notna() & zone_mapping['POWER_ZONE_MAXIMUM'].notna()]['POWER_ZONE_LABEL'].tolist()
                weekly_zones = weekly_zones[weekly_zones['POWER_ZONE_LABEL'].isin(valid_zones)]
                zone_mapping = zone_mapping[zone_mapping['POWER_ZONE_LABEL'].isin(valid_zones)]
                
                # Handle NaN values before converting to int
                zone_mapping['Power Range'] = zone_mapping.apply(
                    lambda row: f"{int(row['POWER_ZONE_MINIMUM'])}-{int(row['POWER_ZONE_MAXIMUM'])}W" 
                    if pd.notna(row['POWER_ZONE_MINIMUM']) and pd.notna(row['POWER_ZONE_MAXIMUM']) 
                    else row['POWER_ZONE_LABEL'], 
                    axis=1
                )
                zone_map_dict = dict(zip(zone_mapping['POWER_ZONE_LABEL'], zone_mapping['Power Range']))
                
                # Pivot to get zones as columns
                weekly_pivot = weekly_zones.pivot(index='Week_Start', columns='POWER_ZONE_LABEL', values='Power Zone Minutes').fillna(0)
                
                # Sort columns by Power Zone Minimum to get lowest zones at bottom (filter out NaN values first)
                zone_mapping_valid = zone_mapping[zone_mapping['POWER_ZONE_MINIMUM'].notna()]
                zone_order = zone_mapping_valid.sort_values('POWER_ZONE_MINIMUM')['POWER_ZONE_LABEL'].tolist()
                weekly_pivot = weekly_pivot.reindex(columns=[col for col in zone_order if col in weekly_pivot.columns])
                
                # Create normalized percentage chart
         
                
                # Calculate weekly totals for normalization
                weekly_totals = weekly_pivot.sum(axis=1)
                weekly_percentage = weekly_pivot.div(weekly_totals, axis=0) * 100
                
                # Create percentage stacked bar chart
                fig_percentage = go.Figure()
                
                for i, zone in enumerate(weekly_percentage.columns):
                    # Get corresponding absolute values for tooltip
                    absolute_values = weekly_pivot[zone]
                    power_range = zone_map_dict.get(zone, zone)  # Use power range if available, otherwise fall back to zone label
                    
                    fig_percentage.add_trace(go.Bar(
                        x=weekly_percentage.index,
                        y=weekly_percentage[zone],
                        name=power_range,
                        marker_color=colors[i % len(colors)],
                        customdata=absolute_values,
                        hovertemplate="<b>Week Starting:</b> %{x}<br>" +
                                    f"<b>Power Zone:</b> {power_range}<br>" +
                                    "<b>Percentage:</b> %{y:.1f}%<br>" +
                                    "<b>Total Time:</b> %{customdata:.2f} minutes<br>" +
                                    "<extra></extra>"
                    ))
                
                fig_percentage.update_layout(
                    # title=f'Weekly Power Zone Distribution (%) for {selected_athlete}',
                    xaxis_title='Week Starting (Monday)',
                    yaxis_title='Percentage (%)',
                    barmode='stack',
                    xaxis={'tickangle': 45}
                )
                
                st.plotly_chart(fig_percentage, width='stretch')
            else:
                st.write("Missing required columns: 'POWER_ZONE_LABEL' and/or 'POWER_ZONE_SECONDS'")
                st.write("Available columns:", df_athlete_data_zones_restrict.columns.tolist())
        else:
            st.write("No power zone data available for the selected athlete.")
