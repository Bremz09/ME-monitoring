#!/usr/bin/env python
import snowflake.connector

# Azure AD with username/password
ctx = snowflake.connector.connect(
    user='SAM.BREMER@HPSNZ.ORG.NZ',
    password='your_azure_ad_password',  # Your Azure AD password
    authenticator='https://login.microsoftonline.com/YOUR_TENANT_ID/oauth2/token',
    account='URHWEIA-HPSNZ'
)
cs = ctx.cursor()
try:
    cs.execute("SELECT current_version()")
    one_row = cs.fetchone()
    print(one_row[0])
finally:
    cs.close()
ctx.close()