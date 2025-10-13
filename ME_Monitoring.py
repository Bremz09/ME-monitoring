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

st.set_page_config(page_title='ME Monitoring - Snowflake Edition',
                  page_icon=":chart_with_upwards_trend:",
                  layout="wide")

# Bypass authentication for testing
authentication_status = True
name = "CNZ"
username = "CNZ"

if authentication_status:
    def get_training_peaks_data():
        """Load Training Peaks data from CSV file (updated nightly from Snowflake)"""
        
        try:
            # Try to load from CSV file
            csv_path = 'data/training_peaks_data.csv'
            
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                
                # Load metadata if available
                metadata_path = 'data/metadata.json'
                if os.path.exists(metadata_path):
                    import json
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
                
                1. 🔄 **First deployment** - Data hasn't been extracted yet
                2. 📁 **File path issue** - Data file is in wrong location  
                3. ⏰ **Extraction pending** - Automated extraction hasn't run
                
                **Next Steps:**
                - Run `extract_data.py` manually to create initial data file
                - Check that automated extraction is scheduled correctly
                - Verify file paths in deployment environment
                """)
                
                return pd.DataFrame()
                
        except Exception as e:
            st.error(f"Error loading training data: {e}")
            return pd.DataFrame()

    def process_training_data(df, athlete, weeks):
        """Process Training Peaks data to create training metrics similar to Excel version"""
        
        # Filter for selected athlete
        df_athlete = df[df['USER_NAME_FIXED'] == athlete].copy()
        
        if df_athlete.empty:
            return pd.DataFrame()
        
        # Convert dates and times
        df_athlete['START_TIME'] = pd.to_datetime(df_athlete['START_TIME'])
        df_athlete['Date'] = df_athlete['START_TIME'].dt.date
        
        # Convert TOTAL_TIME from seconds to hours
        df_athlete['Hours'] = df_athlete['TOTAL_TIME'] / 3600
        
        # Convert ENERGY from joules to kJ
        df_athlete['kJ'] = df_athlete['ENERGY'] / 1000
        
        # Group by date to get daily totals
        daily_data = df_athlete.groupby('Date').agg({
            'Hours': 'sum',
            'TSS': 'sum',
            'kJ': 'sum',
            'DISTANCE': 'sum'
        }).reset_index()
        
        # Convert Date back to datetime for calculations
        daily_data['Date'] = pd.to_datetime(daily_data['Date'])
        
        # Sort by date
        daily_data = daily_data.sort_values('Date')
        
        # Calculate rolling metrics
        daily_data['4_Wk_Hours'] = daily_data['Hours'].rolling(window=28, min_periods=1).mean()
        daily_data['8_Wk_Weighted_H'] = daily_data['Hours'].rolling(window=56, min_periods=1).mean()
        daily_data['8_Wk_Log_H'] = daily_data['Hours'].rolling(window=56, min_periods=1).apply(lambda x: np.log(x.mean() + 1) if x.mean() > 0 else 0)
        
        # Calculate TSS rolling metrics
        daily_data['4_Wk_TSS'] = daily_data['TSS'].rolling(window=28, min_periods=1).mean()
        daily_data['8_Wk_Weighted_TSS'] = daily_data['TSS'].rolling(window=56, min_periods=1).mean()
        
        # Calculate kJ rolling metrics  
        daily_data['4_Wk_kJ'] = daily_data['kJ'].rolling(window=28, min_periods=1).mean()
        daily_data['8_Wk_Weighted_kJ'] = daily_data['kJ'].rolling(window=56, min_periods=1).mean()
        
        # Add week number for tooltip
        daily_data['Week'] = daily_data['Date'].dt.isocalendar().week
        
        # Get last N weeks
        daily_data = daily_data.tail(weeks * 7)  # Approximate weeks to days
        
        return daily_data

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
        if 'POWER_ZONE_MINIMUM' in df_athlete.columns and 'POWER_ZONE_MAXIMUM' in df_athlete.columns:
            zone_data = df_athlete[['POWER_ZONE', 'POWER_ZONE_LABEL', 'POWER_ZONE_MINIMUM', 'POWER_ZONE_MAXIMUM']].drop_duplicates()
            zone_data = zone_data.dropna()
            
            for _, row in zone_data.iterrows():
                if pd.notna(row['POWER_ZONE_MINIMUM']) and pd.notna(row['POWER_ZONE_MAXIMUM']):
                    zone_mapping[row['POWER_ZONE_LABEL']] = f"{int(row['POWER_ZONE_MINIMUM'])}-{int(row['POWER_ZONE_MAXIMUM'])}W"
        
        # Process power zone time data
        if 'POWER_ZONE_SECONDS' in df_athlete.columns and 'POWER_ZONE_LABEL' in df_athlete.columns:
            # Convert seconds to minutes
            df_athlete['POWER_ZONE_MINUTES'] = df_athlete['POWER_ZONE_SECONDS'] / 60
            
            # Create week starting dates (Monday)
            df_athlete['Week_Start'] = df_athlete['START_TIME'].dt.to_period('W-MON').dt.start_time
            
            # Group by week and power zone
            weekly_zones = df_athlete.groupby(['Week_Start', 'POWER_ZONE_LABEL']).agg({
                'POWER_ZONE_MINUTES': 'sum'
            }).reset_index()
            
            return weekly_zones, zone_mapping
        
        return pd.DataFrame(), zone_mapping

    # Main Dashboard
    st.title("🚴‍♂️ ME Monitoring Dashboard (Snowflake Edition)")
    st.markdown("Training data sourced directly from Training Peaks via Snowflake")

    # Load data
    df_training_peaks = get_training_peaks_data()
    
    if df_training_peaks.empty:
        st.error("No data available from Snowflake. Please check your connection.")
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
    
    # Add bars for daily hours
    fig.add_trace(go.Bar(
        x=df_processed["Date"],
        y=df_processed["Hours"],
        name="Daily Hours",
        marker_color="lightblue",
        customdata=df_processed["Week"],
        hovertemplate="<b>Date:</b> %{x}<br>" +
                     "<b>Hours:</b> %{y:.2f}<br>" +
                     "<b>Week:</b> %{customdata}<br>" +
                     "<extra></extra>"
    ))
    
    # Add rolling averages
    fig.add_trace(go.Scatter(
        x=df_processed["Date"],
        y=df_processed["4_Wk_Hours"],
        mode="lines+markers",
        name="4 Wk Average",
        line=dict(color="orange", width=2),
        customdata=df_processed["Week"],
        hovertemplate="<b>Date:</b> %{x}<br>" +
                     "<b>4 Wk Avg:</b> %{y:.2f}<br>" +
                     "<b>Week:</b> %{customdata}<br>" +
                     "<extra></extra>"
    ))
    
    fig.add_trace(go.Scatter(
        x=df_processed["Date"],
        y=df_processed["8_Wk_Weighted_H"],
        mode="lines+markers",
        name="8 Wk Weighted",
        line=dict(color="red", width=2),
        customdata=df_processed["Week"],
        hovertemplate="<b>Date:</b> %{x}<br>" +
                     "<b>8 Wk Weighted:</b> %{y:.2f}<br>" +
                     "<b>Week:</b> %{customdata}<br>" +
                     "<extra></extra>"
    ))
    
    fig.add_trace(go.Scatter(
        x=df_processed["Date"],
        y=df_processed["8_Wk_Log_H"],
        mode="lines+markers",
        name="8 Wk Log",
        line=dict(color="green", width=2),
        customdata=df_processed["Week"],
        hovertemplate="<b>Date:</b> %{x}<br>" +
                     "<b>8 Wk Log:</b> %{y:.2f}<br>" +
                     "<b>Week:</b> %{customdata}<br>" +
                     "<extra></extra>"
    ))
    
    fig.update_layout(
        title=f"Bike Hours and Rolling Metrics (Last {weeks} weeks) - {athlete}",
        xaxis_title="Date",
        yaxis_title="Hours",
        hovermode="x unified"
    )
    
    st.plotly_chart(fig, use_container_width=True)

    # TSS Chart
    st.subheader("Training Stress Score (TSS)")
    
    fig_tss = go.Figure()
    
    # Add bars for daily TSS
    fig_tss.add_trace(go.Bar(
        x=df_processed["Date"],
        y=df_processed["TSS"],
        name="Daily TSS",
        marker_color="lightcoral",
        customdata=df_processed["Week"],
        hovertemplate="<b>Date:</b> %{x}<br>" +
                     "<b>TSS:</b> %{y:.0f}<br>" +
                     "<b>Week:</b> %{customdata}<br>" +
                     "<extra></extra>"
    ))
    
    # Add rolling averages
    fig_tss.add_trace(go.Scatter(
        x=df_processed["Date"],
        y=df_processed["4_Wk_TSS"],
        mode="lines+markers",
        name="4 Wk Average",
        line=dict(color="orange", width=2),
        customdata=df_processed["Week"],
        hovertemplate="<b>Date:</b> %{x}<br>" +
                     "<b>4 Wk Avg TSS:</b> %{y:.0f}<br>" +
                     "<b>Week:</b> %{customdata}<br>" +
                     "<extra></extra>"
    ))
    
    fig_tss.add_trace(go.Scatter(
        x=df_processed["Date"],
        y=df_processed["8_Wk_Weighted_TSS"],
        mode="lines+markers",
        name="8 Wk Weighted",
        line=dict(color="red", width=2),
        customdata=df_processed["Week"],
        hovertemplate="<b>Date:</b> %{x}<br>" +
                     "<b>8 Wk Weighted TSS:</b> %{y:.0f}<br>" +
                     "<b>Week:</b> %{customdata}<br>" +
                     "<extra></extra>"
    ))
    
    fig_tss.update_layout(
        title=f"TSS and Rolling Metrics (Last {weeks} weeks) - {athlete}",
        xaxis_title="Date",
        yaxis_title="TSS",
        hovermode="x unified"
    )
    
    st.plotly_chart(fig_tss, use_container_width=True)

    # kJ Chart
    st.subheader("Energy Expenditure (kJ)")
    
    fig_kj = go.Figure()
    
    # Add bars for daily kJ
    fig_kj.add_trace(go.Bar(
        x=df_processed["Date"],
        y=df_processed["kJ"],
        name="Daily kJ",
        marker_color="lightgreen",
        customdata=df_processed["Week"],
        hovertemplate="<b>Date:</b> %{x}<br>" +
                     "<b>kJ:</b> %{y:.0f}<br>" +
                     "<b>Week:</b> %{customdata}<br>" +
                     "<extra></extra>"
    ))
    
    # Add rolling averages
    fig_kj.add_trace(go.Scatter(
        x=df_processed["Date"],
        y=df_processed["4_Wk_kJ"],
        mode="lines+markers",
        name="4 Wk Average",
        line=dict(color="orange", width=2),
        customdata=df_processed["Week"],
        hovertemplate="<b>Date:</b> %{x}<br>" +
                     "<b>4 Wk Avg kJ:</b> %{y:.0f}<br>" +
                     "<b>Week:</b> %{customdata}<br>" +
                     "<extra></extra>"
    ))
    
    fig_kj.add_trace(go.Scatter(
        x=df_processed["Date"],
        y=df_processed["8_Wk_Weighted_kJ"],
        mode="lines+markers",
        name="8 Wk Weighted",
        line=dict(color="red", width=2),
        customdata=df_processed["Week"],
        hovertemplate="<b>Date:</b> %{x}<br>" +
                     "<b>8 Wk Weighted kJ:</b> %{y:.0f}<br>" +
                     "<b>Week:</b> %{customdata}<br>" +
                     "<extra></extra>"
    ))
    
    fig_kj.update_layout(
        title=f"kJ and Rolling Metrics (Last {weeks} weeks) - {athlete}",
        xaxis_title="Date",
        yaxis_title="kJ",
        hovermode="x unified"
    )
    
    st.plotly_chart(fig_kj, use_container_width=True)

    # Power Zone Distribution
    st.header("Power Zone Distribution")
    
    weekly_zones, zone_mapping = process_power_zone_data(df_training_peaks, athlete)
    
    if not weekly_zones.empty and 'POWER_ZONE_LABEL' in weekly_zones.columns:
        # Create pivot table for power zones
        weekly_pivot = weekly_zones.pivot(index='Week_Start', columns='POWER_ZONE_LABEL', values='POWER_ZONE_MINUTES').fillna(0)
        
        if not weekly_pivot.empty:
            # Sort columns by power zone if we have zone info
            if zone_mapping:
                # Sort by the minimum power value in each zone
                zone_order = []
                for zone in weekly_pivot.columns:
                    if zone in zone_mapping:
                        min_power = int(zone_mapping[zone].split('-')[0].replace('W', ''))
                        zone_order.append((min_power, zone))
                zone_order.sort()
                sorted_zones = [zone for _, zone in zone_order]
                weekly_pivot = weekly_pivot.reindex(columns=sorted_zones)
            
            # Absolute time chart
            st.subheader("Weekly Time Distribution")
            
            fig_weekly = go.Figure()
            colors = px.colors.qualitative.Set3
            
            for i, zone in enumerate(weekly_pivot.columns):
                power_range = zone_mapping.get(zone, zone)
                
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
                title=f'Weekly Power Zone Distribution for {athlete}',
                xaxis_title='Week Starting (Monday)',
                yaxis_title='Time (minutes)',
                barmode='stack',
                xaxis={'tickangle': 45}
            )
            
            st.plotly_chart(fig_weekly, use_container_width=True)
            
            # Percentage chart
            st.subheader("Percentage Distribution")
            
            # Calculate weekly totals for normalization
            weekly_totals = weekly_pivot.sum(axis=1)
            weekly_percentage = weekly_pivot.div(weekly_totals, axis=0) * 100
            
            fig_percentage = go.Figure()
            
            for i, zone in enumerate(weekly_percentage.columns):
                absolute_values = weekly_pivot[zone]
                power_range = zone_mapping.get(zone, zone)
                
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
                title=f'Weekly Power Zone Distribution (%) for {athlete}',
                xaxis_title='Week Starting (Monday)',
                yaxis_title='Percentage (%)',
                barmode='stack',
                xaxis={'tickangle': 45}
            )
            
            st.plotly_chart(fig_percentage, use_container_width=True)
        
        else:
            st.write("No power zone distribution data available for the selected athlete.")
    else:
        st.write("No power zone data available for the selected athlete.")

    # Data Summary Section
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

else:
    st.write("Please log in to access the dashboard")
import snowflake.connector






st.set_page_config(page_title='ME Monitoring',
                  page_icon=":chart_with_upwards_trend:",
                  layout="wide")

# --- USER AUTHENTICATION ---
# Temporarily disabled authentication for testing
# import streamlit_authenticator as stauth 
# import pickle

# For now, bypass authentication
authentication_status = True
name = "CNZ"
username = "CNZ"

if authentication_status:
    def get_training_peaks_data_from_snowflake():
        """Load Training Peaks cycling data from Snowflake view"""
        try:
            # Connect to Snowflake with SSL workarounds
            ctx = snowflake.connector.connect(
                account='URHWEIA-HPSNZ',
                user='SAM.BREMER@HPSNZ.ORG.NZ',
                authenticator='externalbrowser',
                role='PUBLIC',
                warehouse='COMPUTE_WH',
                database='CONSUME',
                schema='SMARTABASE',
                # SSL workarounds
                insecure_mode=False,
                ocsp_response_cache_filename=None
            )
            
            # Query the Training Peaks cycling view
            query = "SELECT * FROM TRAINING_PEAKS_CYCLING_VW"
            df = pd.read_sql(query, ctx)
            
            # Close connection
            ctx.close()
            
            return df
            
        except Exception as e:
            st.warning(f"Snowflake connection issue: {e}")
            st.info("Using demo mode - Snowflake connection will be restored once SSL issues are resolved")
            # Return empty DataFrame for now
            return pd.DataFrame()  # Return empty DataFrame on error
    
    def get_nutrition_data_from_excel():
        df = pd.read_excel(
            io='pages/ME_Monitoring/ME_Nutrition.xlsx',
            engine ='openpyxl',
            sheet_name='Master',
            skiprows=0,
            usecols='A:R',
            nrows=100
            )
        return df
    
    def get_training_data_from_excel(athlete):
        df = pd.read_excel(
            io='pages/ME_Monitoring/ME_Training.xlsx',
            engine ='openpyxl',
            sheet_name=athlete.split(" ")[0],
            skiprows=0,
            usecols='A:P',
            nrows=400
            )
        return df
    
    df_nutrition = get_nutrition_data_from_excel()

    def get_power_zone_data_from_excel(athlete):
        df = pd.read_excel(
            io='pages/ME_Monitoring/ME_Power_Zones.xlsx',
            engine ='openpyxl',
            sheet_name="Sheet1",
            skiprows=0,
            usecols='A:I',
            nrows=20000
            )
        name = athlete.split(" ")[0]+" "+athlete.split(" ")[1]
        df = df[df['Name']==name]
        return df
    
    

    
    c1,c2 = st.columns(2)
    with c1:
        athlete = st.selectbox("Select athlete", options=df_nutrition['Name'].unique())
    with c2:
        weeks = st.slider("Select number of weeks to display", min_value=4, max_value=52, value=52, step=1)
    df_athlete_training = get_training_data_from_excel(athlete).dropna(axis=1, how='all')
    df_zones = get_power_zone_data_from_excel(athlete)
    
    # Load Training Peaks data from Snowflake
    df_training_peaks = get_training_peaks_data_from_snowflake()
    
    # Filter Training Peaks data for selected athlete
    if not df_training_peaks.empty:
        df_athlete_training_peaks = df_training_peaks[df_training_peaks['USER_NAME_FIXED'] == athlete]
    else:
        df_athlete_training_peaks = pd.DataFrame()
    

    

    df_training_sorted = df_athlete_training.sort_values("Date")
    df_training_last52 = df_training_sorted.tail(weeks)
    # Get previous 52 entries
    df_training_prev52 = df_training_sorted.iloc[-weeks - 52:-52] if len(df_training_sorted) >= weeks + 52 else None
    st.header("Training Data")
    fig = go.Figure()

    # Bar for Hours (bike)
    fig.add_trace(go.Bar(
        x=df_training_last52["Date"],
        y=df_training_last52["Hours (bike)"],
        name="Hours (bike)",
        customdata=df_training_last52["Week"],
        hovertemplate="Date: %{x}<br>Hours (bike): %{y}<br>Week: %{customdata}<extra></extra>"
    ))

    # Current year lines
    fig.add_trace(go.Scatter(
        x=df_training_last52["Date"],
        y=df_training_last52["4 Wk Hours"],
        mode="lines+markers",
        name="4 Wk Hours",
        customdata=df_training_last52["Week"],
        hovertemplate="Date: %{x}<br>4 Wk Hours: %{y}<br>Week: %{customdata}<extra></extra>"
    ))
    fig.add_trace(go.Scatter(
        x=df_training_last52["Date"],
        y=df_training_last52["8 Wk Weighted H"],
        mode="lines+markers",
        name="8 Wk Weighted H",
        customdata=df_training_last52["Week"],
        hovertemplate="Date: %{x}<br>8 Wk Weighted H: %{y}<br>Week: %{customdata}<extra></extra>"
    ))
    fig.add_trace(go.Scatter(
        x=df_training_last52["Date"],
        y=df_training_last52["8 Wk Log H"],
        mode="lines+markers",
        name="8 Wk Log H",
        customdata=df_training_last52["Week"],
        hovertemplate="Date: %{x}<br>8 Wk Log H: %{y}<br>Week: %{customdata}<extra></extra>"
    ))

    # Overlay previous year values mapped to current x-axis
    if df_training_prev52 is not None and len(df_training_prev52) == weeks:
        # Align previous year values to current year dates
        prev_4wk = df_training_prev52["4 Wk Hours"].values
        prev_8wk_weighted = df_training_prev52["8 Wk Weighted H"].values
        prev_8wk_log = df_training_prev52["8 Wk Log H"].values
        prev_week = df_training_prev52["Week"].values
        current_dates = df_training_last52["Date"].values

        fig.add_trace(go.Scatter(
            x=current_dates,
            y=prev_4wk,
            mode="lines+markers",
            name="4 Wk Hours (Prev Year)",
            line=dict(dash="dash"),
            customdata=prev_week,
            hovertemplate="Date: %{x}<br>4 Wk Hours (Prev Year): %{y}<br>Week: %{customdata}<extra></extra>"
        ))
        fig.add_trace(go.Scatter(
            x=current_dates,
            y=prev_8wk_weighted,
            mode="lines+markers",
            name="8 Wk Weighted H (Prev Year)",
            line=dict(dash="dash"),
            customdata=prev_week,
            hovertemplate="Date: %{x}<br>8 Wk Weighted H (Prev Year): %{y}<br>Week: %{customdata}<extra></extra>"
        ))
        fig.add_trace(go.Scatter(
            x=current_dates,
            y=prev_8wk_log,
            mode="lines+markers",
            name="8 Wk Log H (Prev Year)",
            line=dict(dash="dash"),
            customdata=prev_week,
            hovertemplate="Date: %{x}<br>8 Wk Log H (Prev Year): %{y}<br>Week: %{customdata}<extra></extra>"
        ))

    fig.update_layout(
        title=f"Bike Hours and Rolling Metrics (Last {weeks} weeks)",
        xaxis_title="Date",
        yaxis_title="Hours"
    )

    st.plotly_chart(fig, use_container_width=True)



    # --- TSS Metrics Plot ---
    fig_tss = go.Figure()
    # Bar for TSS
    fig_tss.add_trace(go.Bar(
        x=df_training_last52["Date"],
        y=df_training_last52["TSS"],
        name="TSS",
        customdata=df_training_last52["Week"],
        hovertemplate="Date: %{x}<br>TSS: %{y}<br>Week: %{customdata}<extra></extra>"
    ))
    # Current year lines
    fig_tss.add_trace(go.Scatter(
        x=df_training_last52["Date"],
        y=df_training_last52["4 Wk TSS"],
        mode="lines+markers",
        name="4 Wk TSS",
        customdata=df_training_last52["Week"],
        hovertemplate="Date: %{x}<br>4 Wk TSS: %{y}<br>Week: %{customdata}<extra></extra>"
    ))
    fig_tss.add_trace(go.Scatter(
        x=df_training_last52["Date"],
        y=df_training_last52["8 Wk Weighted TSS"],
        mode="lines+markers",
        name="8 Wk Weighted TSS",
        customdata=df_training_last52["Week"],
        hovertemplate="Date: %{x}<br>8 Wk Weighted TSS: %{y}<br>Week: %{customdata}<extra></extra>"
    ))
    fig_tss.add_trace(go.Scatter(
        x=df_training_last52["Date"],
        y=df_training_last52["8 Wk Log TSS"],
        mode="lines+markers",
        name="8 Wk Log TSS",
        customdata=df_training_last52["Week"],
        hovertemplate="Date: %{x}<br>8 Wk Log TSS: %{y}<br>Week: %{customdata}<extra></extra>"
    ))
    # Overlay previous year values mapped to current x-axis
    if df_training_prev52 is not None and len(df_training_prev52) == weeks:
        prev_tss = df_training_prev52["TSS"].values
        prev_4wk_tss = df_training_prev52["4 Wk TSS"].values
        prev_8wk_weighted_tss = df_training_prev52["8 Wk Weighted TSS"].values
        prev_8wk_log_tss = df_training_prev52["8 Wk Log TSS"].values
        prev_week = df_training_prev52["Week"].values
        current_dates = df_training_last52["Date"].values
        fig_tss.add_trace(go.Scatter(
            x=current_dates,
            y=prev_4wk_tss,
            mode="lines+markers",
            name="4 Wk TSS (Prev Year)",
            line=dict(dash="dash"),
            customdata=prev_week,
            hovertemplate="Date: %{x}<br>4 Wk TSS (Prev Year): %{y}<br>Week: %{customdata}<extra></extra>"
        ))
        fig_tss.add_trace(go.Scatter(
            x=current_dates,
            y=prev_8wk_weighted_tss,
            mode="lines+markers",
            name="8 Wk Weighted TSS (Prev Year)",
            line=dict(dash="dash"),
            customdata=prev_week,
            hovertemplate="Date: %{x}<br>8 Wk Weighted TSS (Prev Year): %{y}<br>Week: %{customdata}<extra></extra>"
        ))
        fig_tss.add_trace(go.Scatter(
            x=current_dates,
            y=prev_8wk_log_tss,
            mode="lines+markers",
            name="8 Wk Log TSS (Prev Year)",
            line=dict(dash="dash"),
            customdata=prev_week,
            hovertemplate="Date: %{x}<br>8 Wk Log TSS (Prev Year): %{y}<br>Week: %{customdata}<extra></extra>"
        ))
    fig_tss.update_layout(
        title=f"TSS and Rolling Metrics (Last {weeks} weeks)",
        xaxis_title="Date",
        yaxis_title="TSS"
    )
    st.plotly_chart(fig_tss, use_container_width=True)

    # --- kj Metrics Plot ---
    fig_kj = go.Figure()
    # Bar for kj
    fig_kj.add_trace(go.Bar(
        x=df_training_last52["Date"],
        y=df_training_last52["kJ"],
        name="kJ",
        customdata=df_training_last52["Week"],
        hovertemplate="Date: %{x}<br>kJ: %{y}<br>Week: %{customdata}<extra></extra>"
    ))
    # Current year line for 4 Wk kJ
    fig_kj.add_trace(go.Scatter(
        x=df_training_last52["Date"],
        y=df_training_last52["4 Wk kJ"],
        mode="lines+markers",
        name="4 Wk kJ",
        customdata=df_training_last52["Week"],
        hovertemplate="Date: %{x}<br>4 Wk kJ: %{y}<br>Week: %{customdata}<extra></extra>"
    ))
    # Overlay previous year values mapped to current x-axis
    if df_training_prev52 is not None and len(df_training_prev52) == weeks:
        prev_kj = df_training_prev52["kJ"].values
        prev_4wk_kj = df_training_prev52["4 Wk kJ"].values
        prev_week = df_training_prev52["Week"].values
        current_dates = df_training_last52["Date"].values
        fig_kj.add_trace(go.Scatter(
            x=current_dates,
            y=prev_4wk_kj,
            mode="lines+markers",
            name="4 Wk kJ (Prev Year)",
            line=dict(dash="dash"),
            customdata=prev_week,
            hovertemplate="Date: %{x}<br>4 Wk kJ (Prev Year): %{y}<br>Week: %{customdata}<extra></extra>"
        ))
    fig_kj.update_layout(
        title=f"kJ and Rolling Metrics (Last {weeks} weeks)",
        xaxis_title="Date",
        yaxis_title="kJ"
    )
    st.plotly_chart(fig_kj, use_container_width=True)

    # --- Power Zones Plot ---
    st.markdown("---")
    st.header("Power Zone Distribution")
    
    if not df_zones.empty:
        # Check if we have the required columns
        if 'Power Zone Label' in df_zones.columns and 'Power Zone Seconds' in df_zones.columns:
            # Convert seconds to minutes for better readability
            df_zones_copy = df_zones.copy()
            df_zones_copy['Power Zone Minutes'] = (df_zones_copy['Power Zone Seconds'] / 60).round(2)
            
            # Group by Power Zone Label and sum the minutes
            zone_summary = df_zones_copy.groupby('Power Zone Label')['Power Zone Minutes'].sum().reset_index()
            zone_summary = zone_summary.sort_values('Power Zone Minutes', ascending=False)
            zone_summary['Power Zone Minutes'] = zone_summary['Power Zone Minutes'].round(2)
            
            # Also show weekly breakdown if Date column exists
            if 'Date' in df_zones.columns:
                # Convert Date to week for weekly aggregation
                df_zones_copy['Date'] = pd.to_datetime(df_zones_copy['Date'])
                
                # Calculate week start date (Monday) for each date
                df_zones_copy['Week_Start'] = df_zones_copy['Date'] - pd.to_timedelta(df_zones_copy['Date'].dt.weekday, unit='D')
                
                # Filter to show only the selected number of weeks
                latest_week = df_zones_copy['Week_Start'].max()
                cutoff_date = latest_week - pd.Timedelta(weeks=weeks-1)
                df_zones_filtered = df_zones_copy[df_zones_copy['Week_Start'] >= cutoff_date]
                
                # Group by week start and power zone
                weekly_zones = df_zones_filtered.groupby(['Week_Start', 'Power Zone Label'])['Power Zone Minutes'].sum().reset_index()
                weekly_zones['Power Zone Minutes'] = weekly_zones['Power Zone Minutes'].round(2)
                
                # Create mapping from Power Zone Label to power ranges
                zone_mapping = df_zones_filtered.groupby('Power Zone Label').agg({
                    'Power Zone Minimum': 'first',
                    'Power Zone Maximum': 'first'
                }).reset_index()
                zone_mapping['Power Range'] = zone_mapping['Power Zone Minimum'].astype(str) + '-' + zone_mapping['Power Zone Maximum'].astype(str) + 'W'
                zone_map_dict = dict(zip(zone_mapping['Power Zone Label'], zone_mapping['Power Range']))
                
                # Pivot to get zones as columns
                weekly_pivot = weekly_zones.pivot(index='Week_Start', columns='Power Zone Label', values='Power Zone Minutes').fillna(0)
                
                # Sort columns by Power Zone Minimum to get lowest zones at bottom
                zone_order = zone_mapping.sort_values('Power Zone Minimum')['Power Zone Label'].tolist()
                weekly_pivot = weekly_pivot.reindex(columns=[col for col in zone_order if col in weekly_pivot.columns])
                
                # Create stacked bar chart for weekly view
                fig_weekly = go.Figure()
                
                colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#bcbd22', '#17becf']
                
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
                    title=f'Weekly Power Zone Distribution for {athlete}',
                    xaxis_title='Week Starting (Monday)',
                    yaxis_title='Time (minutes)',
                    barmode='stack',
                    xaxis={'tickangle': 45}
                )
                
                st.plotly_chart(fig_weekly, use_container_width=True)
                
                # Create normalized percentage chart
                st.subheader("Percentage Distribution")
                
                # Calculate weekly totals for normalization
                weekly_totals = weekly_pivot.sum(axis=1)
                weekly_percentage = weekly_pivot.div(weekly_totals, axis=0) * 100
                
                # Sort columns by Power Zone Minimum to get lowest zones at bottom
                zone_order = zone_mapping.sort_values('Power Zone Minimum')['Power Zone Label'].tolist()
                weekly_percentage = weekly_percentage.reindex(columns=[col for col in zone_order if col in weekly_percentage.columns])
                
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
                    title=f'Weekly Power Zone Distribution (%) for {athlete}',
                    xaxis_title='Week Starting (Monday)',
                    yaxis_title='Percentage (%)',
                    barmode='stack',
                    xaxis={'tickangle': 45}
                )
                
                st.plotly_chart(fig_percentage, use_container_width=True)
        else:
            st.write("Missing required columns: 'Power Zone Label' and/or 'Power Zone Seconds'")
            st.write("Available columns:", df_zones.columns.tolist())
    else:
        st.write("No power zone data available for the selected athlete.")

    st.markdown("---")
    st.header("Nutrition Data")
    df_athlete_nutrition = df_nutrition[df_nutrition['Name']==athlete].copy()

    

    fig = px.line(df_athlete_nutrition.loc[df_athlete_nutrition['Theme of Consult']=='Body Comp'], x='Date', y=['Height (cm)', 'Body Mass (kg)','Sum8 (mm)','FFM (SFTA; kg)',
                                                     'Corrected Girths (Thigh; cm)','BIA FM (kg)','BIA SMM (kg)'], markers=True)
    fig.update_layout(title=f'Morphology for {athlete}', xaxis_title='Date', yaxis_title='Measurements')
    st.plotly_chart(fig, use_container_width=True)

    fig = px.line(df_athlete_nutrition.loc[df_athlete_nutrition['Theme of Consult']=='Hydration'], x='Date', y=['Hydration status (USG)'], markers=True)
    fig.update_layout(title=f'Hydration status for {athlete}', xaxis_title='Date', yaxis_title='USG')
    st.plotly_chart(fig, use_container_width=True)

    # Training Peaks Data Section
    st.markdown("---")
    st.header("Training Peaks Data")
    
    if not df_athlete_training_peaks.empty:
        st.subheader(f"Training Peaks Summary for {athlete}")
        
        # Display basic statistics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            total_sessions = len(df_athlete_training_peaks)
            st.metric("Total Sessions", total_sessions)
        
        with col2:
            if 'TOTAL_TIME' in df_athlete_training_peaks.columns:
                total_hours = df_athlete_training_peaks['TOTAL_TIME'].sum() / 3600  # Convert seconds to hours
                st.metric("Total Hours", f"{total_hours:.1f}")
        
        with col3:
            if 'DISTANCE' in df_athlete_training_peaks.columns:
                total_distance = df_athlete_training_peaks['DISTANCE'].sum() / 1000  # Convert to km
                st.metric("Total Distance (km)", f"{total_distance:.1f}")
        
        with col4:
            if 'TSS' in df_athlete_training_peaks.columns:
                total_tss = df_athlete_training_peaks['TSS'].sum()
                st.metric("Total TSS", f"{total_tss:.0f}")
        
        # Display data table with key columns
        st.subheader("Recent Training Sessions")
        display_columns = []
        
        # Check which columns exist and add them to display
        available_columns = df_athlete_training_peaks.columns.tolist()
        key_columns = ['START_TIME', 'TITLE', 'WORKOUT_TYPE', 'TOTAL_TIME', 'DISTANCE', 
                      'POWER_AVERAGE', 'POWER_MAXIMUM', 'HEART_RATE_AVERAGE', 'TSS', 'RPE']
        
        for col in key_columns:
            if col in available_columns:
                display_columns.append(col)
        
        if display_columns:
            # Sort by start time and show recent sessions
            df_display = df_athlete_training_peaks.copy()
            if 'START_TIME' in df_display.columns:
                df_display = df_display.sort_values('START_TIME', ascending=False)
            
            # Show top 20 sessions
            st.dataframe(df_display[display_columns].head(20), use_container_width=True)
        
        # Show all available columns for reference
        st.subheader("Available Data Columns")
        st.write("The following columns are available in the Training Peaks dataset:")
        cols_per_row = 4
        for i in range(0, len(available_columns), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, col_name in enumerate(available_columns[i:i+cols_per_row]):
                with cols[j]:
                    st.write(f"• {col_name}")
    
    else:
        st.write(f"No Training Peaks data available for {athlete}")
        if df_training_peaks.empty:
            st.write("Could not connect to Snowflake or view is empty.")
        else:
            available_athletes = df_training_peaks['USER_NAME_FIXED'].unique() if 'USER_NAME_FIXED' in df_training_peaks.columns else []
            st.write(f"Available athletes in Training Peaks data: {', '.join(available_athletes)}")