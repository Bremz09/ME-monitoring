"""
Automated script to sync Training Peaks data from Snowflake to CSV
This script runs on GitHub Actions to keep data fresh without direct Snowflake connection
"""

import snowflake.connector
import pandas as pd
from datetime import datetime
import os
import sys

def sync_data_from_snowflake():
    """Pull latest data from Snowflake and save to CSV"""
    try:
        print("=" * 60)
        print(f"Starting data sync at {datetime.now()}")
        print("=" * 60)
        
        # Get credentials from environment variables (set in GitHub Secrets)
        account = os.environ.get('SNOWFLAKE_ACCOUNT')
        user = os.environ.get('SNOWFLAKE_USER')
        password = os.environ.get('SNOWFLAKE_PASSWORD')
        role = os.environ.get('SNOWFLAKE_ROLE', 'PUBLIC')
        warehouse = os.environ.get('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH')
        database = os.environ.get('SNOWFLAKE_DATABASE', 'CONSUME')
        schema = os.environ.get('SNOWFLAKE_SCHEMA', 'SMARTABASE')
        
        # Validate required credentials
        if not all([account, user, password]):
            raise ValueError("Missing required Snowflake credentials in environment variables")
        
        print(f"Connecting to Snowflake account: {account}")
        print(f"Database: {database}.{schema}")
        
        # Connect to Snowflake
        conn = snowflake.connector.connect(
            account=account,
            user=user,
            password=password,
            role=role,
            warehouse=warehouse,
            database=database,
            schema=schema
        )
        
        print("✅ Successfully connected to Snowflake")
        
        # Query the training peaks data
        table_name = "TRAINING_PEAKS_CYCLING_VW"
        query = f"""
        SELECT *
        FROM {table_name}
        ORDER BY START_TIME DESC
        """
        
        print(f"Querying table: {table_name}")
        df = pd.read_sql(query, conn)
        conn.close()
        
        print(f"✅ Retrieved {len(df)} rows from Snowflake")
        
        # Display column info
        print(f"Columns: {list(df.columns)}")
        
        # Save to CSV
        csv_path = 'data/training_peaks_data.csv'
        
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        # Save the data
        df.to_csv(csv_path, index=False)
        print(f"✅ Saved data to {csv_path}")
        
        # Create metadata file with sync info
        metadata = {
            'last_sync': datetime.now().isoformat(),
            'row_count': len(df),
            'columns': list(df.columns),
            'date_range': {
                'earliest': str(df['START_TIME'].min()) if 'START_TIME' in df.columns else 'N/A',
                'latest': str(df['START_TIME'].max()) if 'START_TIME' in df.columns else 'N/A'
            }
        }
        
        import json
        with open('data/metadata.json', 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print(f"✅ Updated metadata")
        print(f"Date range: {metadata['date_range']['earliest']} to {metadata['date_range']['latest']}")
        
        print("=" * 60)
        print("✅ Data sync completed successfully!")
        print("=" * 60)
        return True
        
    except Exception as e:
        print("=" * 60)
        print(f"❌ Error syncing data: {e}")
        print("=" * 60)
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = sync_data_from_snowflake()
    sys.exit(0 if success else 1)
