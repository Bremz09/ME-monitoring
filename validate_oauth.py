#!/usr/bin/env python
import snowflake.connector

# OAuth token authentication
ctx = snowflake.connector.connect(
    user='SAM.BREMER@HPSNZ.ORG.NZ',
    authenticator='oauth',
    token='YOUR_OAUTH_TOKEN',  # Get this from Azure AD
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