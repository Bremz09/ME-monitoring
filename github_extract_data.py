"""
GitHub Actions data extraction script
Connects to Snowflake and extracts training data
"""

import os
import sys
import pandas as pd
import snowflake.connector
from datetime import datetime
import json

def extract_data():
    """Extract training peaks data from Snowflake"""
    
    print("=" * 70)
    print(f"Starting data extraction at {datetime.now()}")
    print("=" * 70)
    
    # Get credentials from environment variables (GitHub Secrets)
    account = os.getenv('SNOWFLAKE_ACCOUNT')
    user = os.getenv('SNOWFLAKE_USER')
    password = os.getenv('SNOWFLAKE_PASSWORD')
    role = os.getenv('SNOWFLAKE_ROLE', 'PUBLIC')
    warehouse = os.getenv('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH')
    database = os.getenv('SNOWFLAKE_DATABASE', 'CONSUME')
    schema = os.getenv('SNOWFLAKE_SCHEMA', 'SMARTABASE')
    
    # Validate credentials
    if not account or not user:
        print("❌ Missing required Snowflake credentials")
        print("Please configure GitHub Secrets:")
        print("  - SNOWFLAKE_ACCOUNT")
        print("  - SNOWFLAKE_USER")
        print("  - SNOWFLAKE_PASSWORD (or other auth method)")
        return False
    
    if not password:
        print("⚠️ No password found. Trying alternative authentication...")
        # Could add key-based auth here if needed
        print("❌ No authentication method available")
        return False
    
    try:
        print(f"Connecting to Snowflake account: {account}")
        print(f"User: {user}")
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
        
        print("✅ Successfully connected to Snowflake!")
        
        # Query the data
        table_name = "TRAINING_PEAKS_CYCLING_VW"
        query = f"""
        SELECT *
        FROM {table_name}
        ORDER BY START_TIME DESC
        """
        
        print(f"Querying table: {table_name}...")
        df = pd.read_sql(query, conn)
        conn.close()
        
        print(f"✅ Retrieved {len(df)} rows")
        print(f"Columns: {list(df.columns)}")
        
        # Create data directory if needed
        os.makedirs('data', exist_ok=True)
        os.makedirs('data/backup', exist_ok=True)
        
        # Save to CSV
        csv_path = 'data/training_peaks_data.csv'
        df.to_csv(csv_path, index=False)
        print(f"✅ Saved to {csv_path}")
        
        # Create metadata
        metadata = {
            'last_sync': datetime.now().isoformat(),
            'row_count': len(df),
            'columns': list(df.columns),
            'date_range': {
                'earliest': str(df['START_TIME'].min()) if 'START_TIME' in df.columns else 'N/A',
                'latest': str(df['START_TIME'].max()) if 'START_TIME' in df.columns else 'N/A'
            },
            'source': 'GitHub Actions automated sync'
        }
        
        with open('data/metadata.json', 'w') as f:
            json.dump(metadata, f, indent=2)
        
        print(f"✅ Updated metadata")
        print(f"Date range: {metadata['date_range']['earliest']} to {metadata['date_range']['latest']}")
        
        print("=" * 70)
        print("✅ Data extraction completed successfully!")
        print("=" * 70)
        return True
        
    except snowflake.connector.errors.DatabaseError as e:
        error_msg = str(e)
        print("=" * 70)
        print("❌ Snowflake Connection Error")
        print("=" * 70)
        
        if "IP/Token" in error_msg and "not allowed" in error_msg:
            print("\n⚠️ IP WHITELIST ISSUE DETECTED")
            print("\nThis GitHub Actions runner IP is blocked by Snowflake network policy.")
            print("\nTo fix this, your Snowflake admin needs to whitelist GitHub Actions IPs.")
            print("\nSee SNOWFLAKE_IP_WHITELIST_REQUEST.md for details to send to admin.")
            print("\n📋 Current runner IP may be visible in error above.")
            print("\n💡 Temporary workaround: Run manual sync from whitelisted computer")
            print("   then commit/push to GitHub.")
        else:
            print(f"Error: {error_msg}")
        
        print("=" * 70)
        return False
        
    except Exception as e:
        print("=" * 70)
        print(f"❌ Unexpected error: {e}")
        print("=" * 70)
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = extract_data()
    sys.exit(0 if success else 1)
