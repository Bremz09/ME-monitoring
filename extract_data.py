#!/usr/bin/env python
"""
Automated Training Peaks Data Extractor
Runs locally at midnight to pull data from Snowflake and commit to repo
"""

import pandas as pd
import snowflake.connector
from datetime import datetime
import os
import subprocess
import sys

def extract_training_peaks_data():
    """Extract data from Snowflake and save to CSV"""
    
    print(f"Starting data extraction at {datetime.now()}")
    
    try:
        # Connect to Snowflake using Azure AD (local access)
        print("Connecting to Snowflake...")
        ctx = snowflake.connector.connect(
            account='URHWEIA-HPSNZ',
            user='SAM.BREMER@HPSNZ.ORG.NZ',
            authenticator='externalbrowser',
            role='PUBLIC',
            warehouse='COMPUTE_WH',
            database='CONSUME',
            schema='SMARTABASE'
        )
        
        # Query the Training Peaks cycling view
        print("Extracting training data...")
        query = "SELECT * FROM TRAINING_PEAKS_CYCLING_VW ORDER BY START_TIME"
        df = pd.read_sql(query, ctx)
        
        # Close connection
        ctx.close()
        
        # Save to CSV with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_filename = 'data/training_peaks_data.csv'
        
        # Create data directory if it doesn't exist
        os.makedirs('data', exist_ok=True)
        
        # Save current data
        df.to_csv(csv_filename, index=False)
        
        # Also save with timestamp for backup
        backup_filename = f'data/backup/training_peaks_data_{timestamp}.csv'
        os.makedirs('data/backup', exist_ok=True)
        df.to_csv(backup_filename, index=False)
        
        print(f"Data extracted: {len(df)} records")
        print(f"Saved to: {csv_filename}")
        
        # Create metadata file
        metadata = {
            'last_updated': datetime.now().isoformat(),
            'record_count': len(df),
            'date_range_start': str(df['START_TIME'].min()) if not df.empty else None,
            'date_range_end': str(df['START_TIME'].max()) if not df.empty else None,
            'athletes': df['USER_NAME_FIXED'].unique().tolist() if not df.empty else []
        }
        
        import json
        with open('data/metadata.json', 'w') as f:
            json.dump(metadata, f, indent=2)
        
        return True, csv_filename, len(df)
        
    except Exception as e:
        print(f"Error extracting data: {e}")
        return False, None, 0

def commit_and_push_data():
    """Git commit and push the updated data"""
    
    try:
        # Change to script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        os.chdir(script_dir)
        
        print("Committing data to git...")
        
        # Add files
        subprocess.run(['git', 'add', 'data/'], check=True)
        
        # Commit with timestamp
        commit_message = f"Automated data update - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        subprocess.run(['git', 'commit', '-m', commit_message], check=True)
        
        # Push to remote
        subprocess.run(['git', 'push'], check=True)
        
        print("Data committed and pushed successfully!")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"Git operation failed: {e}")
        return False
    except Exception as e:
        print(f"Error with git operations: {e}")
        return False

def main():
    """Main execution function"""
    
    print("=" * 50)
    print("Training Peaks Data Extraction Started")
    print("=" * 50)
    
    # Extract data
    success, filename, record_count = extract_training_peaks_data()
    
    if success:
        print(f"✅ Data extraction successful: {record_count} records")
        
        # Commit and push
        if commit_and_push_data():
            print("✅ Git commit and push successful")
            print("🚀 Deployed app will have updated data within minutes!")
        else:
            print("❌ Git operations failed")
            sys.exit(1)
    else:
        print("❌ Data extraction failed")
        sys.exit(1)
    
    print("=" * 50)
    print("Training Peaks Data Extraction Completed")
    print("=" * 50)

if __name__ == "__main__":
    main()