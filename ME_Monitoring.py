#!/usr/bin/env python
# coding: utf-8



import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime






st.set_page_config(page_title='ME Monitoring',
                  page_icon=":chart_with_upwards_trend:",
                  layout="wide")

# --- USER AUTHENTICATION ---
import streamlit_authenticator as stauth 
import pickle
# load hashed passwords
with open("hashed_pw.pkl","rb") as file:
    hashed_passwords = pickle.load(file)



usernames = ['CNZ']
names = ['CNZ']


credentials = {"usernames":{}}
        
for uname,name,pwd in zip(usernames,names,hashed_passwords):
    user_dict = {"name": name, "password": pwd}
    credentials["usernames"].update({uname: user_dict})
        
authenticator = stauth.Authenticate(credentials, "CNZPD", "abcdef", cookie_expiry_days=30)

name, authentication_status, username = authenticator.login("Login", "main")

if authentication_status == False:
    st.error("Username/password is incorrect")

if authentication_status == None:
    st.warning("Please enter your username and password")

if authentication_status:
    @st.cache_data
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
    
    @st.cache_data
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

    @st.cache_data
    def get_power_zone_data_from_excel(athlete):
        df = pd.read_excel(
            io='pages/ME_Monitoring/ME_Power_Zones.xlsx',
            engine ='openpyxl',
            sheet_name="Sheet1",
            skiprows=0,
            usecols='A:J',
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
                
                # Pivot to get zones as columns
                weekly_pivot = weekly_zones.pivot(index='Week_Start', columns='Power Zone Label', values='Power Zone Minutes').fillna(0)
                
                # Create stacked bar chart for weekly view
                fig_weekly = go.Figure()
                
                colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#bcbd22', '#17becf']
                
                for i, zone in enumerate(weekly_pivot.columns):
                    fig_weekly.add_trace(go.Bar(
                        x=weekly_pivot.index,
                        y=weekly_pivot[zone],
                        name=zone,
                        marker_color=colors[i % len(colors)],
                        hovertemplate="<b>Week Starting:</b> %{x}<br>" +
                                    f"<b>Power Zone:</b> {zone}<br>" +
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
                
                # Create percentage stacked bar chart
                fig_percentage = go.Figure()
                
                for i, zone in enumerate(weekly_percentage.columns):
                    # Get corresponding absolute values for tooltip
                    absolute_values = weekly_pivot[zone]
                    
                    fig_percentage.add_trace(go.Bar(
                        x=weekly_percentage.index,
                        y=weekly_percentage[zone],
                        name=zone,
                        marker_color=colors[i % len(colors)],
                        customdata=absolute_values,
                        hovertemplate="<b>Week Starting:</b> %{x}<br>" +
                                    f"<b>Power Zone:</b> {zone}<br>" +
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