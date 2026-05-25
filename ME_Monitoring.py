#!/usr/bin/env python
# coding: utf-8

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import snowflake.connector
import numpy as np
import os
import json

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


ATHLETES = [
    "Aaron Gate",
    "Ally Wollaston",
    "Bryony Botha",
    "Emily Shearman",
    "George Jackson",
    "Jessie Hodges",
    "Keegan Hornblow",
    "Marshall Erwood",
    "Nicholas Kergozou De La Boessiere",
    "Samantha Donnelly",
    "Thomas Sexton",
]


def get_athlete_list():
    return ATHLETES


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


# ── UI components ──────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([3, 3, 2])

with col1:
    try:
        available_athletes = get_athlete_list()
    except Exception as e:
        st.error(f"❌ Could not load athlete list: {e}")
        available_athletes = []
    selected_athlete = st.selectbox("Select athlete", options=available_athletes) if available_athletes else None

with col2:
    weeks = st.slider("Select number of past weeks", min_value=4, max_value=52, value=12, step=1)

with col3:
    st.write("")
    bike_only = st.toggle("Bike only", value=False)

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

# Create tabs for different chart types
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Training Time", "TSS", "Energy (kJ)", "Strength", "Power Zones", "Power Zones %"])

# TAB 1: Weekly Training Time
with tab1:
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
