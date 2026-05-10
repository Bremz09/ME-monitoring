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
                POWER_ZONE_SECONDS, TSB, TSS, ENERGY
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
col1, col2 = st.columns(2)

with col1:
    try:
        available_athletes = get_athlete_list()
    except Exception as e:
        st.error(f"❌ Could not load athlete list: {e}")
        available_athletes = []
    selected_athlete = st.selectbox("Select athlete", options=available_athletes) if available_athletes else None

with col2:
    weeks = st.slider("Select number of past weeks", min_value=4, max_value=52, value=12, step=1)

# ── Load athlete data ──────────────────────────────────────────────────────────
# Safe defaults so tab code never hits NameError
df_raw = pd.DataFrame()
df_athlete_data_zones = pd.DataFrame()
df_athlete_data_zones_restrict = pd.DataFrame()
current_week_start = pd.Timestamp.now().normalize()
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
df_raw
# Add WEEK column - week starts on Monday, current week = 0
if not df_raw.empty:
    # Define the start of the current week (Monday of this week)
    today = pd.Timestamp.now().normalize()
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
else:
    df_raw_restrict = pd.DataFrame()
# Create tabs for different chart types
tab1, tab2, tab3, tab4, tab5 = st.tabs(["Training Time", "TSS", "Energy (kJ)", "Power Zones", "Power Zones %"])

# TAB 1: Weekly Training Time
with tab1:
    if not df_athlete_data_zones_restrict.empty and 'POWER_ZONE_SECONDS' in df_athlete_data_zones_restrict.columns:
        
        # Group by weeks and sum the power zone seconds for restricted data
        weekly_time = df_athlete_data_zones_restrict.groupby('WEEKS_PAST')['POWER_ZONE_SECONDS'].sum().reset_index()
        
        # Convert seconds to hours and round to 2 decimal places
        weekly_time['HOURS'] = (weekly_time['POWER_ZONE_SECONDS'] / 3600).round(2)
        
        # Calculate the Monday date for each week
        weekly_time['WEEK_START_DATE'] = weekly_time['WEEKS_PAST'].apply(
            lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
        )
    
        # Sort by weeks_past for proper display
        weekly_time = weekly_time.sort_values('WEEKS_PAST')
    
    # Calculate rolling 4-week average from the original (unrestricted) data
    if not df_athlete_data_zones_restrict.empty and 'POWER_ZONE_SECONDS' in df_athlete_data_zones_restrict.columns and not df_athlete_data_zones.empty:
        # Group all data by weeks and sum the power zone seconds
        all_weekly_time = df_athlete_data_zones.groupby('WEEKS_PAST')['POWER_ZONE_SECONDS'].sum().reset_index()
        all_weekly_time['HOURS'] = (all_weekly_time['POWER_ZONE_SECONDS'] / 3600).round(2)
        all_weekly_time = all_weekly_time.sort_values('WEEKS_PAST')
        
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
        
        # Calculate week start dates for rolling average
        all_weekly_time['WEEK_START_DATE'] = all_weekly_time['WEEKS_PAST'].apply(
            lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
        )
        
        # Filter rolling average data to match the display range
        rolling_avg_display = all_weekly_time[
            all_weekly_time['WEEKS_PAST'].isin(weekly_time['WEEKS_PAST'])
        ].copy()
    
        # Create the combined chart using plotly graph objects for more control
        st.subheader("Weekly Training Time with Rolling Averages")
        fig = go.Figure()
        
        # Add bar chart for weekly hours
        fig.add_trace(go.Bar(
            x=weekly_time['WEEK_START_DATE'],
            y=weekly_time['HOURS'],
            name='Weekly Hours',
            marker_color='lightblue',
            hovertemplate='Hours: %{y}<extra></extra>'
        ))
        
        # Add rolling average lines if data exists
        if not df_athlete_data_zones.empty and len(rolling_avg_display) > 0:
            # 4-week rolling average
            fig.add_trace(go.Scatter(
                x=rolling_avg_display['WEEK_START_DATE'],
                y=rolling_avg_display['ROLLING_4WK_AVG'],
                mode='lines+markers',
                name='4-Week Rolling Average',
                line=dict(color='red', width=3),
                marker=dict(size=6),
                hovertemplate='4-Week Avg: %{y} hours<extra></extra>'
            ))
            
            # 8-week centrally weighted rolling average
            fig.add_trace(go.Scatter(
                x=rolling_avg_display['WEEK_START_DATE'],
                y=rolling_avg_display['ROLLING_8WK_WEIGHTED_AVG'],
                mode='lines+markers',
                name='8-Week Weighted Average',
                line=dict(color='green', width=3),
                marker=dict(size=6),
                hovertemplate='8-Week Weighted Avg: %{y} hours<extra></extra>'
            ))
            
            # 8-week log average
            fig.add_trace(go.Scatter(
                x=rolling_avg_display['WEEK_START_DATE'],
                y=rolling_avg_display['ROLLING_8WK_LOG_AVG'],
                mode='lines+markers',
                name='8-Week Log Average',
                line=dict(color='purple', width=3),
                marker=dict(size=6),
                hovertemplate='8-Week Log Avg: %{y} hours<extra></extra>'
            ))
        
        # Update layout for better appearance
        fig.update_layout(
            # title=f'Last {weeks} weeks',
            xaxis_title="Week Starting (Monday)",
            yaxis_title="Training Time (Hours)",
            showlegend=True,
            hovermode='x unified'
        )
        
        # Format x-axis to show dates nicely
        fig.update_xaxes(tickformat="%Y-%m-%d")
        
        st.plotly_chart(fig, width='stretch')
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
    
        # Calculate rolling averages from the full unrestricted raw data
        if not df_raw.empty:
            # Group all data by weeks and sum the TSS
            all_weekly_tss = df_raw.groupby('WEEKS_PAST')['TSS'].sum().reset_index()
            all_weekly_tss['TSS'] = all_weekly_tss['TSS'].round(1)
            all_weekly_tss = all_weekly_tss.sort_values('WEEKS_PAST')
            
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
        st.subheader("Weekly TSS with Rolling Averages")
        fig_tss = go.Figure()
        
        # Add bar chart for weekly TSS
        fig_tss.add_trace(go.Bar(
            x=weekly_tss['WEEK_START_DATE'],
            y=weekly_tss['TSS'],
            name='Weekly TSS',
            marker_color='lightcoral',
            hovertemplate='TSS: %{y}<extra></extra>'
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
            xaxis_title="Week Starting (Monday)",
            yaxis_title="TSS",
            showlegend=True,
            hovermode='x unified'
        )
        
        fig_tss.update_xaxes(tickformat="%Y-%m-%d")
        st.plotly_chart(fig_tss, width='stretch')
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
        
        # Calculate rolling averages from the original (unrestricted) data
        if not df_athlete_data_zones.empty:
            # Group all data by weeks and sum the ENERGY
            all_weekly_energy = df_athlete_data_zones.groupby('WEEKS_PAST')['ENERGY'].sum().reset_index()
            all_weekly_energy['ENERGY_KJ'] = (all_weekly_energy['ENERGY'] / 1000).round(1)
            all_weekly_energy = all_weekly_energy.sort_values('WEEKS_PAST')
            
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
        st.subheader("Weekly Energy (kJ) with Rolling Averages")
        fig_energy = go.Figure()
        
        # Add bar chart for weekly energy
        fig_energy.add_trace(go.Bar(
            x=weekly_energy['WEEK_START_DATE'],
            y=weekly_energy['ENERGY_KJ'],
            name='Weekly Energy (kJ)',
            marker_color='lightgreen',
            hovertemplate='Energy: %{y} kJ<extra></extra>'
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
            xaxis_title="Week Starting (Monday)",
            yaxis_title="Energy (kJ)",
            showlegend=True,
            hovermode='x unified'
        )
        
        fig_energy.update_xaxes(tickformat="%Y-%m-%d")
        st.plotly_chart(fig_energy, width='stretch')
    else:
        st.info("No data available for the selected athlete and time period.")

# TAB 4: Power Zone Distribution (Raw)
with tab4:
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

# TAB 5: Power Zone Distribution (Percentage)
with tab5:
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
