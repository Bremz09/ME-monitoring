"""
Test Snowflake connection with Azure AD authentication
"""
import snowflake.connector
import pandas as pd
import streamlit as st

def test_snowflake_connection():
    """Test the Snowflake connection and explore available tables"""
    try:
        print("Testing Snowflake connection with Azure AD authentication...")
        
        # Load secrets from Streamlit
        conn = snowflake.connector.connect(
            account=st.secrets["snowflake"]["account"],
            user=st.secrets["snowflake"]["user"],
            authenticator=st.secrets["snowflake"]["authenticator"],  # externalbrowser for Azure AD
            role=st.secrets["snowflake"]["role"],
            warehouse=st.secrets["snowflake"]["warehouse"],
            database=st.secrets["snowflake"]["database"],
            schema=st.secrets["snowflake"]["schema"]
        )
        
        print("✅ Successfully connected to Snowflake!")
        
        # Get cursor
        cursor = conn.cursor()
        
        # List all tables in the schema
        print("\n🔍 Discovering available tables...")
        cursor.execute("SHOW TABLES")
        all_tables = cursor.fetchall()
        
        print(f"\n📊 Found {len(all_tables)} tables in {st.secrets['snowflake']['database']}.{st.secrets['snowflake']['schema']}:")
        table_names = []
        for table in all_tables:
            table_name = table[1]
            table_names.append(table_name)
            print(f"  - {table_name}")
        
        # Look for training-related tables (including the known correct one)
        training_tables = [name for name in table_names if any(keyword in name.upper() for keyword in ['TRAINING', 'PEAKS', 'TP', 'EXERCISE', 'WORKOUT', 'SMARTABASE', 'CYCLING'])]
        
        # Check specifically for the known table
        if "TRAINING_PEAKS_CYCLING_VW" in table_names:
            print(f"\n✅ Found the correct table: TRAINING_PEAKS_CYCLING_VW")
            training_tables = ["TRAINING_PEAKS_CYCLING_VW"] + [t for t in training_tables if t != "TRAINING_PEAKS_CYCLING_VW"]
        
        if training_tables:
            print(f"\n🏃 Found potential training-related tables:")
            for table in training_tables:
                print(f"  - {table}")
                
                # Sample each training table to see its structure
                try:
                    sample_query = f"SELECT * FROM {table} LIMIT 3"
                    sample_df = pd.read_sql(sample_query, conn)
                    print(f"\n📋 Sample from {table}:")
                    print(f"   Columns: {list(sample_df.columns)}")
                    print(f"   Rows: {len(sample_df)}")
                    if not sample_df.empty:
                        print(f"   Sample data:")
                        for col in sample_df.columns[:5]:  # Show first 5 columns
                            print(f"     {col}: {sample_df[col].iloc[0] if len(sample_df) > 0 else 'N/A'}")
                except Exception as sample_error:
                    print(f"   ❌ Could not sample {table}: {sample_error}")
        else:
            print("\n⚠️ No obvious training-related tables found.")
            print("Here are all available tables - one might contain the training data:")
            for table in table_names:
                print(f"  - {table}")
        
        conn.close()
        return True
        
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        return False

if __name__ == "__main__":
    test_snowflake_connection()