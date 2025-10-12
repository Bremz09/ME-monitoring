#!/usr/bin/env python
import snowflake.connector

# Read and execute the SQL file
def execute_sql_file(cursor, file_path):
    with open(file_path, 'r') as file:
        sql_content = file.read()
    cursor.execute(sql_content)
    return cursor.fetchall()

# Connect to Snowflake
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
    # Execute the view creation script
    execute_sql_file(cs, 'create_training_peaks_cycling_view.sql')
    print("View TRAINING_PEAKS_CYCLING_VW created successfully!")
    
    # Test the view
    cs.execute("SELECT COUNT(*) FROM TRAINING_PEAKS_CYCLING_VW")
    count = cs.fetchone()
    print(f"View contains {count[0]} records")
    
except Exception as e:
    print(f"Error: {e}")
finally:
    cs.close()
    ctx.close()