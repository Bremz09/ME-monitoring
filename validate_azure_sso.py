#!/usr/bin/env python
import snowflake.connector

# Azure AD SSO - Opens browser for authentication
ctx = snowflake.connector.connect(
    user='SAM.BREMER@HPSNZ.ORG.NZ',
    authenticator='externalbrowser',  # This will open a browser for Azure AD login
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