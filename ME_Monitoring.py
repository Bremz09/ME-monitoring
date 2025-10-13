#!/usr/bin/env python
# coding: utf-8

import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import numpy as np
import os
import json

st.set_page_config(page_title='ME Monitoring Dashboard',
                  page_icon=":chart_with_upwards_trend:",
                  layout="wide")

# Cached function to load Training Peaks data from CSV
@st.cache_data
def get_training_peaks_data():
    """Load Training Peaks data from CSV file (updated by extract_data.py)"""
    
    try:
        csv_path = 'data/training_peaks_data.csv'
        
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
            
            # Load metadata if available
            metadata_path = 'data/metadata.json'
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                
                # Display data freshness info
                last_updated = datetime.fromisoformat(metadata['last_updated'])
                time_diff = datetime.now() - last_updated
                
                if time_diff.total_seconds() < 3600:  # Less than 1 hour
                    freshness_color = "🟢"
                elif time_diff.total_seconds() < 86400:  # Less than 24 hours
                    freshness_color = "🟡"
                else:  # More than 24 hours
                    freshness_color = "🔴"
                
                st.sidebar.markdown(f"""
                **Data Freshness** {freshness_color}
                
                📅 **Last Updated**: {last_updated.strftime('%Y-%m-%d %H:%M')}
                
                📊 **Records**: {metadata['record_count']:,}
                
                👥 **Athletes**: {len(metadata['athletes'])}
                
                📈 **Date Range**: 
                {metadata['date_range_start'][:10] if metadata['date_range_start'] else 'N/A'} to 
                {metadata['date_range_end'][:10] if metadata['date_range_end'] else 'N/A'}
                """)
            
            return df
        
        else:
            st.error("❌ Training data file not found!")
            st.markdown("""
            **Data File Missing**
            
            The training data file (`data/training_peaks_data.csv`) was not found. This could mean:
            
            1. 🔄 **First run** - Data hasn't been extracted yet
            2. 📁 **File path issue** - Data file is in wrong location  
            3. ⏰ **Extraction needed** - Run `extract_data.py` to get fresh data
            
            **Next Steps:**
            - Run `extract_data.py` to create/update the data file
            - Check that the `data/` directory exists
            - Verify file paths are correct
            """)
            
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Error loading training data: {e}")
        return pd.DataFrame()

def process_training_data(df, athlete, weeks):
    """Process Training Peaks data to create weekly training metrics"""
    
    # Filter for selected athlete
    df_athlete = df[df['USER_NAME_FIXED'] == athlete].copy()
    
    if df_athlete.empty:
        return pd.DataFrame()
    
    # Convert dates and times
    df_athlete['START_TIME'] = pd.to_datetime(df_athlete['START_TIME'])
    df_athlete['Date'] = df_athlete['START_TIME'].dt.date
    df_athlete['Date'] = pd.to_datetime(df_athlete['Date'])
    
    # Convert TOTAL_TIME from seconds to hours
    df_athlete['Hours'] = df_athlete['TOTAL_TIME'] / 3600
    
    # Convert ENERGY from joules to kJ
    df_athlete['kJ'] = df_athlete['ENERGY'] / 1000
    
    # Create week starting Monday (Monday = 0 in week calculation)
    # Get the start of the week (Monday) for each date
    df_athlete['Week_Start'] = df_athlete['Date'] - pd.to_timedelta(df_athlete['Date'].dt.dayofweek, unit='D')
    
    # Group by week to get weekly totals
    weekly_data = df_athlete.groupby('Week_Start').agg({
        'Hours': 'sum',
        'TSS': 'sum', 
        'kJ': 'sum',
        'DISTANCE': 'sum'
    }).reset_index()
    
    # Sort by week start date
    weekly_data = weekly_data.sort_values('Week_Start')
    
    # Calculate rolling metrics (using weeks instead of days)
    weekly_data['4_Wk_Hours'] = weekly_data['Hours'].rolling(window=4, min_periods=1).mean()
    weekly_data['8_Wk_Weighted_H'] = weekly_data['Hours'].rolling(window=8, min_periods=1).mean()
    weekly_data['8_Wk_Log_H'] = weekly_data['Hours'].rolling(window=8, min_periods=1).apply(lambda x: np.log(x.mean() + 1) if x.mean() > 0 else 0)
    
    # Calculate TSS rolling metrics
    weekly_data['4_Wk_TSS'] = weekly_data['TSS'].rolling(window=4, min_periods=1).mean()
    weekly_data['8_Wk_Weighted_TSS'] = weekly_data['TSS'].rolling(window=8, min_periods=1).mean()
    
    # Calculate kJ rolling metrics  
    weekly_data['4_Wk_kJ'] = weekly_data['kJ'].rolling(window=4, min_periods=1).mean()
    weekly_data['8_Wk_Weighted_kJ'] = weekly_data['kJ'].rolling(window=8, min_periods=1).mean()
    
    # Add week end date for better labeling
    weekly_data['Week_End'] = weekly_data['Week_Start'] + pd.Timedelta(days=6)
    
    # Create week label (e.g., "Oct 7-13" or "Week 41")
    weekly_data['Week_Label'] = weekly_data.apply(lambda row: 
        f"{row['Week_Start'].strftime('%b %d')}-{row['Week_End'].strftime('%d')}", axis=1)
    
    # Get last N weeks
    weekly_data = weekly_data.tail(weeks)
    
    return weekly_data

def process_power_zone_data(df, athlete):
    """Process power zone data from Training Peaks"""
    
    # Filter for selected athlete
    df_athlete = df[df['USER_NAME_FIXED'] == athlete].copy()
    
    if df_athlete.empty:
        return pd.DataFrame(), {}
    
    # Convert dates
    df_athlete['START_TIME'] = pd.to_datetime(df_athlete['START_TIME'])
    
    # Create power zone mapping (if available)
    zone_mapping = {}
    
    # Look for power zone columns in the data
    zone_columns = [col for col in df_athlete.columns if 'ZONE' in col.upper()]
    
    if zone_columns:
        # Create week starting dates (Monday)
        df_athlete['Week_Start'] = df_athlete['START_TIME'].dt.to_period('W-MON').dt.start_time
        
        # Group by week and sum zone data
        weekly_zones = df_athlete.groupby('Week_Start')[zone_columns].sum().reset_index()
        
        return weekly_zones, zone_mapping
    
    return pd.DataFrame(), zone_mapping

# Main Dashboard
st.title("🚴‍♂️ ME Monitoring Dashboard")
st.markdown("Training data from Training Peaks (updated via extract_data.py)")

# Load data
df_training_peaks = get_training_peaks_data()

if df_training_peaks.empty:
    st.warning("No training data available. Please run `extract_data.py` to load data.")
    st.stop()

# Get available athletes
available_athletes = sorted(df_training_peaks['USER_NAME_FIXED'].unique())

# Controls
c1, c2 = st.columns(2)
with c1:
    athlete = st.selectbox("Select athlete", options=available_athletes)
with c2:
    weeks = st.slider("Select number of weeks to display", min_value=4, max_value=52, value=26, step=1)

# Process training data
df_processed = process_training_data(df_training_peaks, athlete, weeks)

if df_processed.empty:
    st.warning(f"No training data available for {athlete}")
    st.stop()

# Training Data Section
st.header("Training Data")

# Hours Chart
fig = go.Figure()

# Add bars for weekly hours
fig.add_trace(go.Bar(
    x=df_processed["Week_Start"],
    y=df_processed["Hours"],
    name="Weekly Hours",
    marker_color="lightblue",
    customdata=df_processed["Week_Label"],
    hovertemplate="<b>Week:</b> %{customdata}<br>" +
                 "<b>Total Hours:</b> %{y:.2f}<br>" +
                 "<extra></extra>"
))

# Add rolling averages
fig.add_trace(go.Scatter(
    x=df_processed["Week_Start"],
    y=df_processed["4_Wk_Hours"],
    mode="lines+markers",
    name="4 Wk Average",
    line=dict(color="orange", width=2),
    customdata=df_processed["Week_Label"],
    hovertemplate="<b>Week:</b> %{customdata}<br>" +
                 "<b>4 Wk Avg:</b> %{y:.2f}<br>" +
                 "<extra></extra>"
))

fig.add_trace(go.Scatter(
    x=df_processed["Week_Start"],
    y=df_processed["8_Wk_Weighted_H"],
    mode="lines+markers",
    name="8 Wk Weighted",
    line=dict(color="red", width=2),
    customdata=df_processed["Week_Label"],
    hovertemplate="<b>Week:</b> %{customdata}<br>" +
                 "<b>8 Wk Weighted:</b> %{y:.2f}<br>" +
                 "<extra></extra>"
))

fig.add_trace(go.Scatter(
    x=df_processed["Week_Start"],
    y=df_processed["8_Wk_Log_H"],
    mode="lines+markers",
    name="8 Wk Log",
    line=dict(color="green", width=2),
    customdata=df_processed["Week_Label"],
    hovertemplate="<b>Week:</b> %{customdata}<br>" +
                 "<b>8 Wk Log:</b> %{y:.2f}<br>" +
                 "<extra></extra>"
))

fig.update_layout(
    title=f"Weekly Bike Hours and Rolling Metrics (Last {weeks} weeks) - {athlete}",
    xaxis_title="Week",
    yaxis_title="Hours",
    hovermode="x unified"
)

st.plotly_chart(fig, use_container_width=True)

# TSS Chart
st.subheader("Training Stress Score (TSS)")

fig_tss = go.Figure()

# Add bars for weekly TSS
fig_tss.add_trace(go.Bar(
    x=df_processed["Week_Start"],
    y=df_processed["TSS"],
    name="Weekly TSS",
    marker_color="lightcoral",
    customdata=df_processed["Week_Label"],
    hovertemplate="<b>Week:</b> %{customdata}<br>" +
                 "<b>Total TSS:</b> %{y:.0f}<br>" +
                 "<extra></extra>"
))

# Add rolling averages
fig_tss.add_trace(go.Scatter(
    x=df_processed["Week_Start"],
    y=df_processed["4_Wk_TSS"],
    mode="lines+markers",
    name="4 Wk Average",
    line=dict(color="orange", width=2),
    customdata=df_processed["Week_Label"],
    hovertemplate="<b>Week:</b> %{customdata}<br>" +
                 "<b>4 Wk Avg TSS:</b> %{y:.0f}<br>" +
                 "<extra></extra>"
))

fig_tss.add_trace(go.Scatter(
    x=df_processed["Week_Start"],
    y=df_processed["8_Wk_Weighted_TSS"],
    mode="lines+markers",
    name="8 Wk Weighted",
    line=dict(color="red", width=2),
    customdata=df_processed["Week_Label"],
    hovertemplate="<b>Week:</b> %{customdata}<br>" +
                 "<b>8 Wk Weighted TSS:</b> %{y:.0f}<br>" +
                 "<extra></extra>"
))

fig_tss.update_layout(
    title=f"Weekly TSS and Rolling Metrics (Last {weeks} weeks) - {athlete}",
    xaxis_title="Week",
    yaxis_title="TSS",
    hovermode="x unified"
)

st.plotly_chart(fig_tss, use_container_width=True)

# kJ Chart
st.subheader("Energy Expenditure (kJ)")

fig_kj = go.Figure()

# Add bars for weekly kJ
fig_kj.add_trace(go.Bar(
    x=df_processed["Week_Start"],
    y=df_processed["kJ"],
    name="Weekly kJ",
    marker_color="lightgreen",
    customdata=df_processed["Week_Label"],
    hovertemplate="<b>Week:</b> %{customdata}<br>" +
                 "<b>Total kJ:</b> %{y:.0f}<br>" +
                 "<extra></extra>"
))

# Add rolling averages
fig_kj.add_trace(go.Scatter(
    x=df_processed["Week_Start"],
    y=df_processed["4_Wk_kJ"],
    mode="lines+markers",
    name="4 Wk Average",
    line=dict(color="orange", width=2),
    customdata=df_processed["Week_Label"],
    hovertemplate="<b>Week:</b> %{customdata}<br>" +
                 "<b>4 Wk Avg kJ:</b> %{y:.0f}<br>" +
                 "<extra></extra>"
))

fig_kj.add_trace(go.Scatter(
    x=df_processed["Week_Start"],
    y=df_processed["8_Wk_Weighted_kJ"],
    mode="lines+markers",
    name="8 Wk Weighted",
    line=dict(color="red", width=2),
    customdata=df_processed["Week_Label"],
    hovertemplate="<b>Week:</b> %{customdata}<br>" +
                 "<b>8 Wk Weighted kJ:</b> %{y:.0f}<br>" +
                 "<extra></extra>"
))

fig_kj.update_layout(
    title=f"Weekly kJ and Rolling Metrics (Last {weeks} weeks) - {athlete}",
    xaxis_title="Week",
    yaxis_title="kJ",
    hovermode="x unified"
)

st.plotly_chart(fig_kj, use_container_width=True)

# Power Zone Distribution
st.header("Power Zone Distribution")

weekly_zones, zone_mapping = process_power_zone_data(df_training_peaks, athlete)

if not weekly_zones.empty:
    st.subheader("Weekly Power Zone Time")
    
    # Display available power zone data
    zone_columns = [col for col in weekly_zones.columns if col != 'Week_Start']
    
    if zone_columns:
        fig_zones = go.Figure()
        colors = px.colors.qualitative.Set3
        
        for i, zone_col in enumerate(zone_columns):
            fig_zones.add_trace(go.Bar(
                x=weekly_zones['Week_Start'],
                y=weekly_zones[zone_col],
                name=zone_col,
                marker_color=colors[i % len(colors)]
            ))
        
        fig_zones.update_layout(
            title=f'Weekly Power Zone Distribution for {athlete}',
            xaxis_title='Week Starting (Monday)',
            yaxis_title='Time/Value',
            barmode='stack'
        )
        
        st.plotly_chart(fig_zones, use_container_width=True)
    else:
        st.write("No power zone columns found in the data.")
        
else:
    st.write("No power zone data available for the selected athlete.")

# Training Summary
st.header("Training Summary")

# Calculate summary statistics
col1, col2, col3, col4 = st.columns(4)

with col1:
    total_sessions = len(df_training_peaks[df_training_peaks['USER_NAME_FIXED'] == athlete])
    st.metric("Total Sessions", total_sessions)

with col2:
    total_hours = df_processed['Hours'].sum()
    st.metric("Total Hours", f"{total_hours:.1f}")

with col3:
    total_tss = df_processed['TSS'].sum()
    st.metric("Total TSS", f"{total_tss:.0f}")

with col4:
    total_kj = df_processed['kJ'].sum()
    st.metric("Total kJ", f"{total_kj:.0f}")

# Recent Sessions Table
st.subheader("Recent Training Sessions")

# Get recent sessions for selected athlete
df_athlete_sessions = df_training_peaks[df_training_peaks['USER_NAME_FIXED'] == athlete].copy()
df_athlete_sessions['START_TIME'] = pd.to_datetime(df_athlete_sessions['START_TIME'])
df_athlete_sessions = df_athlete_sessions.sort_values('START_TIME', ascending=False)

# Select key columns for display
display_columns = ['START_TIME', 'TITLE', 'WORKOUT_TYPE', 'TOTAL_TIME', 'DISTANCE', 
                  'POWER_AVERAGE', 'POWER_MAXIMUM', 'HEART_RATE_AVERAGE', 'TSS', 'RPE']

# Filter to available columns
available_display_cols = [col for col in display_columns if col in df_athlete_sessions.columns]

if available_display_cols:
    # Format the data for better display
    df_display = df_athlete_sessions[available_display_cols].head(20).copy()
    
    # Format time columns
    if 'TOTAL_TIME' in df_display.columns:
        df_display['TOTAL_TIME'] = (df_display['TOTAL_TIME'] / 3600).round(2)  # Convert to hours
    
    if 'DISTANCE' in df_display.columns:
        df_display['DISTANCE'] = (df_display['DISTANCE'] / 1000).round(2)  # Convert to km
    
    st.dataframe(df_display, use_container_width=True)
else:
    st.write("No session data available to display")

# Debug Information
if st.sidebar.checkbox("Show Debug Info"):
    st.subheader("Debug Information")
    st.write("**Data Shape:**", df_training_peaks.shape)
    st.write("**Available Athletes:**", available_athletes)
    st.write("**Available Columns:**")
    
    # Show columns in a more organized way
    available_columns = list(df_training_peaks.columns)
    cols_per_row = 4
    for i in range(0, len(available_columns), cols_per_row):
        cols = st.columns(cols_per_row)
        for j, col_name in enumerate(available_columns[i:i+cols_per_row]):
            with cols[j]:
                st.write(f"• {col_name}")