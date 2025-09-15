#!/usr/bin/env python
# coding: utf-8



import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from PIL import Image

import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import norm
from datetime import datetime
import statsmodels.api as sm
import streamlit.components.v1 as components
from pandas.api.types import (
is_categorical_dtype,
is_datetime64_any_dtype,
is_numeric_dtype,
is_object_dtype,
)




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
    
    df_nutrition = get_nutrition_data_from_excel()

    df_nutrition

    athlete = st.selectbox("Select athlete", options=df_nutrition['Name'].unique())

    df_athlete_nutrition = df_nutrition[df_nutrition['Name']==athlete].copy()

    df_athlete_nutrition

    fig = px.line(df_athlete_nutrition.loc[df_athlete_nutrition['Theme of Consult']=='Body Comp'], x='Date', y=['Height (cm)', 'Body Mass (kg)','Sum8 (mm)','FFM (SFTA; kg)',
                                                     'Corrected Girths (Thigh; cm)','BIA FM (kg)','BIA SMM (kg)'], markers=True)
    fig.update_layout(title=f'Morphology for {athlete}', xaxis_title='Date', yaxis_title='Measurements')
    st.plotly_chart(fig, use_container_width=True)

    fig = px.line(df_athlete_nutrition.loc[df_athlete_nutrition['Theme of Consult']=='Hydration'], x='Date', y=['Hydration status (USG)'], markers=True)
    fig.update_layout(title=f'Hydration status for {athlete}', xaxis_title='Date', yaxis_title='USG')
    st.plotly_chart(fig, use_container_width=True)