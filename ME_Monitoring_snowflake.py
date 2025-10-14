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
import pickle
import streamlit_authenticator as stauth

st.set_page_config(page_title='ME Monitoring',
                  page_icon=":chart_with_upwards_trend:",
                  layout="wide")

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
    
    # Create filtered copy with only rows that have power zone data
    df_zones = df_training_peaks[df_training_peaks["POWER_ZONE_LABEL"].notna()].copy()
    
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
        

    df_athlete_data_zones =df_zones = df_athlete_data[df_athlete_data["POWER_ZONE_LABEL"].notna()].sort_values(["START_TIME","POWER_ZONE_MINIMUM"], ascending=[False,True]).copy()
    
    # Add WEEK column - week starts on Monday, current week (Oct 13, 2025) = 0
    if not df_athlete_data_zones.empty:
        # Define the start of the current week (Monday, October 13, 2025)
        current_week_start = pd.Timestamp('2025-10-13').normalize()
        
        # Calculate week number for each row
        df_athlete_data_zones['WEEKS_PAST'] = df_athlete_data_zones['START_TIME'].apply(
            lambda x: ((current_week_start - pd.Timestamp(x).normalize()).days + pd.Timestamp(x).weekday()) // 7
        )
        
        # Reorder columns to put WEEKS_PAST in 7th position
        cols = df_athlete_data_zones.columns.tolist()
        if 'WEEKS_PAST' in cols:
            cols.remove('WEEKS_PAST')
            cols.insert(6, 'WEEKS_PAST')  # 7th position (0-indexed is 6)
            df_athlete_data_zones = df_athlete_data_zones[cols]
        
        # Filter to show recent weeks (1 to weeks) and same weeks from previous year (53 to 52+weeks)
        recent_weeks = list(range(1, weeks + 1))  # weeks 1 to N
        previous_year_weeks = list(range(53, 53 + weeks))  # weeks 53 to 52+N
        weeks_to_include = recent_weeks + previous_year_weeks
        
        df_athlete_data_zones = df_athlete_data_zones[
            df_athlete_data_zones['WEEKS_PAST'].isin(weeks_to_include)
        ].copy()
    weeks_to_include
    df_athlete_data_zones