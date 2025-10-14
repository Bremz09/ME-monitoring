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




st.set_page_config(page_title='ME Monitoring',
                  page_icon=":chart_with_upwards_trend:",
                  layout="wide")

# --- USER AUTHENTICATION ---
# Temporarily disabled authentication for testing
# Bypass authentication for testing
authentication_status = True
name = "CNZ"
username = "CNZ"

if authentication_status:
    
    @st.cache_data
    def load_training_peaks_data():
        """Load training peaks data from CSV with caching"""
        try:
            df = pd.read_csv('data/training_peaks_data.csv')
            # Convert date column to datetime
            if 'START_TIME' in df.columns:
                df['START_TIME'] = pd.to_datetime(df['START_TIME'])
            return df
        except FileNotFoundError:
            st.error("Training Peaks data file not found. Please run the data extraction script first.")
            return pd.DataFrame()
        except Exception as e:
            st.error(f"Error loading training peaks data: {e}")
            return pd.DataFrame()
    
    # Load data
    df_training_peaks = load_training_peaks_data()
    
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
    
    def get_training_data_from_csv(athlete):
        """Get training data for specific athlete from Training Peaks CSV"""
        if df_training_peaks.empty:
            return pd.DataFrame()
        
        # Filter for the specific athlete
        athlete_data = df_training_peaks[df_training_peaks['USER_NAME_FIXED'] == athlete].copy()
        
        if athlete_data.empty:
            return pd.DataFrame()
            
        # Convert necessary columns and calculate metrics similar to Excel version
        # Add weekly aggregation logic here to match Excel functionality
        athlete_data = athlete_data.sort_values('START_TIME')
        
        # Create a simplified dataframe with key metrics for compatibility
        training_summary = pd.DataFrame({
            'Date': athlete_data['START_TIME'],
            'Hours (bike)': athlete_data['TOTAL_TIME'] / 3600 if 'TOTAL_TIME' in athlete_data.columns else 0,  # Convert seconds to hours
            'TSS': athlete_data['TSS'] if 'TSS' in athlete_data.columns else 0,
            'kJ': athlete_data['ENERGY'] if 'ENERGY' in athlete_data.columns else 0,
            'Week': athlete_data['START_TIME'].dt.isocalendar().week if 'START_TIME' in athlete_data.columns else 0
        })
        
        # Calculate rolling averages to match Excel functionality
        training_summary['4 Wk Hours'] = training_summary['Hours (bike)'].rolling(window=28, min_periods=1).mean()
        training_summary['8 Wk Weighted H'] = training_summary['Hours (bike)'].ewm(span=56).mean()
        training_summary['8 Wk Log H'] = training_summary['Hours (bike)'].rolling(window=56, min_periods=1).mean()
        
        # Add TSS rolling averages
        training_summary['4 Wk TSS'] = training_summary['TSS'].rolling(window=28, min_periods=1).mean()
        training_summary['8 Wk Weighted TSS'] = training_summary['TSS'].ewm(span=56).mean()
        training_summary['8 Wk Log TSS'] = training_summary['TSS'].rolling(window=56, min_periods=1).mean()
        
        # Add kJ rolling averages
        training_summary['4 Wk kJ'] = training_summary['kJ'].rolling(window=28, min_periods=1).mean()
        training_summary['8 Wk Weighted kJ'] = training_summary['kJ'].ewm(span=56).mean()
        training_summary['8 Wk Log kJ'] = training_summary['kJ'].rolling(window=56, min_periods=1).mean()
        
        return training_summary
    
    # Nutrition data functionality temporarily disabled - now using Training Peaks CSV for athlete selection
    # df_nutrition = get_nutrition_data_from_excel()

    def get_power_zone_data_from_csv(athlete):
        """Get power zone data for specific athlete from Training Peaks CSV"""
        if df_training_peaks.empty:
            return pd.DataFrame()
        
        # Filter for the specific athlete
        athlete_data = df_training_peaks[df_training_peaks['USER_NAME_FIXED'] == athlete].copy()
        
        if athlete_data.empty:
            return pd.DataFrame()
            
        # Extract unique power zone information for the athlete
        power_zones = athlete_data[['POWER_ZONE', 'POWER_ZONE_LABEL', 'POWER_ZONE_MINIMUM', 
                                   'POWER_ZONE_MAXIMUM', 'POWER_THRESHOLD']].dropna()
        
        if power_zones.empty:
            return pd.DataFrame()
            
        # Remove duplicates and create a clean power zone dataframe
        power_zones_unique = power_zones.drop_duplicates(subset=['POWER_ZONE'])
        power_zones_unique = power_zones_unique.sort_values('POWER_ZONE')
        
        # Rename columns to match expected format
        power_zones_unique = power_zones_unique.rename(columns={
            'POWER_ZONE': 'Zone',
            'POWER_ZONE_LABEL': 'Zone_Label',
            'POWER_ZONE_MINIMUM': 'Min_Power',
            'POWER_ZONE_MAXIMUM': 'Max_Power',
            'POWER_THRESHOLD': 'Threshold'
        })
        
        power_zones_unique['Name'] = athlete  # Add name column for compatibility
        
        return power_zones_unique
    
    

    
    c1,c2 = st.columns(2)
    with c1:
        # Get athlete list from Training Peaks CSV data
        if not df_training_peaks.empty and 'USER_NAME_FIXED' in df_training_peaks.columns:
            available_athletes = sorted(df_training_peaks['USER_NAME_FIXED'].unique())
            athlete = st.selectbox("Select athlete", options=available_athletes)
        else:
            st.error("No athlete data available. Please check the data file.")
            athlete = None
    with c2:
        weeks = st.slider("Select number of weeks to display", min_value=4, max_value=52, value=52, step=1)
    
    if athlete:
        df_athlete_training = get_training_data_from_csv(athlete).dropna(axis=1, how='all')
        df_zones = get_power_zone_data_from_csv(athlete)
        
        # Filter Training Peaks data for selected athlete
        if not df_training_peaks.empty:
            df_athlete_training_peaks = df_training_peaks[df_training_peaks['USER_NAME_FIXED'] == athlete]
        else:
            df_athlete_training_peaks = pd.DataFrame()
        
        if not df_athlete_training.empty:
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
    # Nutrition data section temporarily disabled - focusing on Training Peaks data
    # st.header("Nutrition Data")
    # df_athlete_nutrition = df_nutrition[df_nutrition['Name']==athlete].copy()
    
    # fig = px.line(df_athlete_nutrition.loc[df_athlete_nutrition['Theme of Consult']=='Body Comp'], x='Date', y=['Height (cm)', 'Body Mass (kg)','Sum8 (mm)','FFM (SFTA; kg)',
    #                                                  'Corrected Girths (Thigh; cm)','BIA FM (kg)','BIA SMM (kg)'], markers=True)
    # fig.update_layout(title=f'Morphology for {athlete}', xaxis_title='Date', yaxis_title='Measurements')
    # st.plotly_chart(fig, use_container_width=True)

    # fig = px.line(df_athlete_nutrition.loc[df_athlete_nutrition['Theme of Consult']=='Hydration'], x='Date', y=['Hydration status (USG)'], markers=True)
    # fig.update_layout(title=f'Hydration status for {athlete}', xaxis_title='Date', yaxis_title='USG')
    # st.plotly_chart(fig, use_container_width=True)

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