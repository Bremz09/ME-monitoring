#!/usr/bin/env python
import snowflake.connector

# Gets the version
ctx = snowflake.connector.connect(
    account='URHWEIA-HPSNZ',
    user='SAM.BREMER@HPSNZ.ORG.NZ',
    authenticator='externalbrowser',
    role='PUBLIC',
    warehouse='COMPUTE_WH',
    database='CONSUME',
    schema='SMARTABASE'
    )
cs = ctx.cursor()
try:
    cs.execute("SELECT current_version()")
    one_row = cs.fetchone()
    print(one_row[0])
finally:
    cs.close()
ctx.close()