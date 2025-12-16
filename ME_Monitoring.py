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
import os
import json
import pickle
import streamlit_authenticator as stauth

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

# --- USER AUTHENTICATION ---

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
    def load_training_peaks_data():
        """Load training peaks data from CSV (synced from Snowflake via GitHub Actions)"""
        try:
            # Try loading from CSV first (GitHub Actions keeps this updated)
            csv_path = 'data/training_peaks_data.csv'
            
            if os.path.exists(csv_path):
                st.info("📊 Loading data from synchronized CSV file...")
                df = pd.read_csv(csv_path)
                
                # Check metadata for last sync time
                metadata_path = 'data/metadata.json'
                if os.path.exists(metadata_path):
                    import json
                    with open(metadata_path, 'r') as f:
                        metadata = json.load(f)
                    last_sync = metadata.get('last_sync', 'Unknown')
                    st.success(f"✅ Loaded {len(df)} rows | Last updated: {last_sync}")
                else:
                    st.success(f"✅ Loaded {len(df)} rows from CSV")
                
                # Convert date column to datetime
                if 'START_TIME' in df.columns:
                    df['START_TIME'] = pd.to_datetime(df['START_TIME'], format='mixed', errors='coerce')
                
                return df
            
            # Fallback: Try Snowflake connection (for local development)
            st.warning("CSV file not found, attempting direct Snowflake connection...")
            
            # Check if secrets are available
            if "snowflake" not in st.secrets:
                st.error("❌ No CSV file found and no Snowflake secrets configured!")
                st.info("For deployed apps, data should be synced via GitHub Actions.")
                raise Exception("No data source available")
            
            st.info("Connecting to Snowflake...")
            
            # Snowflake connection parameters
            conn_params = {
                "account": st.secrets["snowflake"]["account"],
                "user": st.secrets["snowflake"]["user"],
                "role": st.secrets["snowflake"]["role"],
                "warehouse": st.secrets["snowflake"]["warehouse"],
                "database": st.secrets["snowflake"]["database"],
                "schema": st.secrets["snowflake"]["schema"]
            }
            
            # Add authentication method based on what's available
            if "authenticator" in st.secrets["snowflake"]:
                auth_method = st.secrets["snowflake"]["authenticator"]
                if auth_method == "externalbrowser":
                    st.warning("⚠️ External browser authentication detected. This works locally but not on Streamlit Cloud.")
                conn_params["authenticator"] = auth_method
            elif "password" in st.secrets["snowflake"]:
                conn_params["password"] = st.secrets["snowflake"]["password"]
            else:
                st.error("❌ No authentication method found in secrets!")
                raise Exception("No password or authenticator found in secrets")
            
            conn = snowflake.connector.connect(**conn_params)
            
            st.success("Connected to Snowflake successfully!")
            
            # First, let's explore the schema to find tables
            cursor = conn.cursor()
            
            # List all tables in the current schema
            try:
                cursor.execute("SHOW TABLES")
                all_tables = cursor.fetchall()
                table_names = [table[1] for table in all_tables]
                st.write(f"Available tables in {st.secrets['snowflake']['database']}.{st.secrets['snowflake']['schema']}:")
                st.write(table_names)
            except Exception as table_error:
                st.warning(f"Could not list tables: {table_error}")
                table_names = []
            
            # Try to find training peaks related tables
            training_tables = [name for name in table_names if any(keyword in name.upper() for keyword in ['TRAINING', 'PEAKS', 'TP', 'EXERCISE', 'WORKOUT'])]
            
            if training_tables:
                st.write("Found potential training-related tables:", training_tables)
            
            # Try different possible table names (prioritize the known correct table)
            possible_tables = [
                "TRAINING_PEAKS_CYCLING_VW",  # The correct table name
                "TRAINING_PEAKS_DATA",
                "TRAININGPEAKS_DATA", 
                "TRAINING_PEAKS",
                "TRAININGPEAKS",
                "TP_DATA",
                "EXERCISE_DATA",
                "WORKOUT_DATA"
            ] + training_tables  # Add any discovered training tables
            
            df = None
            successful_table = None
            
            for table_name in possible_tables:
                try:
                    # Try to query a small sample first
                    sample_query = f"SELECT * FROM {table_name} LIMIT 5"
                    sample_df = pd.read_sql(sample_query, conn)
                    
                    if not sample_df.empty:
                        st.write(f"Sample data from {table_name}:")
                        st.write(sample_df.head())
                        st.write(f"Columns in {table_name}: {list(sample_df.columns)}")
                        
                        # If this looks like training data, get the full dataset
                        if any(col in sample_df.columns for col in ['START_TIME', 'POWER_ZONE_LABEL', 'TSS', 'ENERGY']):
                            query = f"""
                            SELECT *
                            FROM {table_name}
                            ORDER BY START_TIME DESC
                            """
                            df = pd.read_sql(query, conn)
                            successful_table = table_name
                            st.success(f"Successfully loaded {len(df)} rows from table: {table_name}")
                            break
                        
                except Exception as table_error:
                    continue  # Try next table
            
            conn.close()
            
            if df is None:
                st.error("No suitable training peaks table found. Please check the table names above and update the query.")
                raise Exception("No accessible training peaks table found with expected columns")
            
            # Convert date column to datetime with flexible format
            if 'START_TIME' in df.columns:
                df['START_TIME'] = pd.to_datetime(df['START_TIME'], format='mixed', errors='coerce')
            
            return df
            
        except Exception as e:
            st.error(f"Error loading training peaks data from Snowflake: {e}")
            
            # Fallback to CSV if Snowflake connection fails
            try:
                st.warning("Falling back to CSV file...")
                df = pd.read_csv('data/training_peaks_data.csv')
                if 'START_TIME' in df.columns:
                    df['START_TIME'] = pd.to_datetime(df['START_TIME'], format='mixed', errors='coerce')
                return df
            except Exception as csv_error:
                st.error(f"CSV fallback also failed: {csv_error}")
                return pd.DataFrame()
            except Exception as csv_error:
                st.error(f"CSV fallback also failed: {csv_error}")
                return pd.DataFrame()
    
    # Load data
    df_training_peaks = load_training_peaks_data()
    
    # Create filtered copy with only rows that have power zone data
    # Check if POWER_ZONE_LABEL column exists
    if not df_training_peaks.empty and 'POWER_ZONE_LABEL' in df_training_peaks.columns:
        df_zones = df_training_peaks[df_training_peaks["POWER_ZONE_LABEL"].notna()].copy()
    else:
        df_zones = pd.DataFrame()
        if not df_training_peaks.empty:
            st.warning("POWER_ZONE_LABEL column not found in the data. Available columns: " + ", ".join(df_training_peaks.columns.tolist()))
    
    # UI Components
    col1, col2 = st.columns(2)
    
    with col1:
        # Get unique athletes from the data
        if not df_training_peaks.empty and 'USER_NAME_FIXED' in df_training_peaks.columns:
            available_athletes = sorted(df_training_peaks['USER_NAME_FIXED'].unique())
            selected_athlete = st.selectbox("Select athlete", options=available_athletes)
        else:
            st.error("No athlete data available. Please check the data file.")
            selected_athlete = None
    
    with col2:
        weeks = st.slider("Select number of past weeks", min_value=4, max_value=52, value=12, step=1)
    
    # Filter data based on selected athlete and weeks
    if selected_athlete:
        # Filter by athlete
        df_athlete_data = df_training_peaks[df_training_peaks['USER_NAME_FIXED'] == selected_athlete].copy()
        
        # Check if we have power zone data for this athlete
        if 'POWER_ZONE_LABEL' in df_athlete_data.columns:
            df_athlete_data_zones = df_athlete_data[df_athlete_data["POWER_ZONE_LABEL"].notna()].sort_values(["START_TIME","POWER_ZONE_MINIMUM"], ascending=[False,True]).copy()
        else:
            df_athlete_data_zones = pd.DataFrame()
            st.warning("No power zone data available - POWER_ZONE_LABEL column not found.")
    
    # Add WEEK column - week starts on Monday, current week = 0
    if not df_athlete_data_zones.empty:
        # Define the start of the current week (Monday of this week)
        today = pd.Timestamp.now().normalize()
        days_since_monday = today.weekday()  # Monday = 0, Sunday = 6
        current_week_start = today - pd.Timedelta(days=days_since_monday)
        
        # Calculate week number for each row
        # For each date, find its Monday (start of its week), then count weeks from current Monday
        df_athlete_data_zones['WEEKS_PAST'] = df_athlete_data_zones['START_TIME'].apply(
            lambda x: (current_week_start - (pd.Timestamp(x).normalize() - pd.Timedelta(days=pd.Timestamp(x).weekday()))).days // 7
        )
        
        # Reorder columns to put WEEKS_PAST in 7th position
        cols = df_athlete_data_zones.columns.tolist()
        if 'WEEKS_PAST' in cols:
            cols.remove('WEEKS_PAST')
            cols.insert(6, 'WEEKS_PAST')  # 7th position (0-indexed is 6)
            df_athlete_data_zones = df_athlete_data_zones[cols]
        
        # Filter to show only recent weeks (1 to weeks)
        recent_weeks = list(range(1, weeks + 1))  # weeks 1 to N
        
        df_athlete_data_zones_restrict = df_athlete_data_zones[
            df_athlete_data_zones['WEEKS_PAST'].isin(recent_weeks)
        ].copy()
    
    df_athlete_data_zones_restrict
    
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
        if not df_athlete_data_zones.empty:
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
            
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("No power zone data available for the selected athlete and time period.")
    
    # TAB 2: Weekly TSS
    with tab2:
        if not df_athlete_data_zones_restrict.empty and 'TSS' in df_athlete_data_zones_restrict.columns:
            
            # Group by weeks and sum the TSS for restricted data
            weekly_tss = df_athlete_data_zones_restrict.groupby('WEEKS_PAST')['TSS'].sum().reset_index()
            weekly_tss['TSS'] = weekly_tss['TSS'].round(1)
            
            # Calculate the Monday date for each week
            weekly_tss['WEEK_START_DATE'] = weekly_tss['WEEKS_PAST'].apply(
                lambda weeks_back: current_week_start - pd.Timedelta(weeks=weeks_back)
            )
            
            # Sort by weeks_past for proper display
            weekly_tss = weekly_tss.sort_values('WEEKS_PAST')
        
        # Calculate rolling averages from the original (unrestricted) data
        if not df_athlete_data_zones.empty:
            # Group all data by weeks and sum the TSS
            all_weekly_tss = df_athlete_data_zones.groupby('WEEKS_PAST')['TSS'].sum().reset_index()
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
        if not df_athlete_data_zones.empty and len(rolling_avg_tss_display) > 0:
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
        st.plotly_chart(fig_tss, use_container_width=True)
    
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
        st.plotly_chart(fig_energy, use_container_width=True)
    
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
                zone_mapping['Power Range'] = zone_mapping['POWER_ZONE_MINIMUM'].astype(int).astype(str) + '-' + zone_mapping['POWER_ZONE_MAXIMUM'].astype(int).astype(str) + 'W'
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
                
                st.plotly_chart(fig_weekly, use_container_width=True)
    
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
                zone_mapping['Power Range'] = zone_mapping['POWER_ZONE_MINIMUM'].astype(int).astype(str) + '-' + zone_mapping['POWER_ZONE_MAXIMUM'].astype(int).astype(str) + 'W'
                zone_map_dict = dict(zip(zone_mapping['POWER_ZONE_LABEL'], zone_mapping['Power Range']))
                
                # Pivot to get zones as columns
                weekly_pivot = weekly_zones.pivot(index='Week_Start', columns='POWER_ZONE_LABEL', values='Power Zone Minutes').fillna(0)
                
                # Sort columns by Power Zone Minimum to get lowest zones at bottom
                zone_order = zone_mapping.sort_values('POWER_ZONE_MINIMUM')['POWER_ZONE_LABEL'].tolist()
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
                
                st.plotly_chart(fig_percentage, use_container_width=True)
            else:
                st.write("Missing required columns: 'POWER_ZONE_LABEL' and/or 'POWER_ZONE_SECONDS'")
                st.write("Available columns:", df_athlete_data_zones_restrict.columns.tolist())
        else:
            st.write("No power zone data available for the selected athlete.")