# GitHub Actions Auto-Sync Setup Instructions

## Overview
Your app now uses GitHub Actions to automatically sync data from Snowflake every hour. This means:
- ✅ FREE automated updates
- ✅ Your computer can be off
- ✅ Streamlit Cloud reads from the synced CSV file
- ✅ Data updates hourly without direct Snowflake connection

## Setup Steps

### 1. Push Your Code to GitHub

```powershell
# Navigate to your project directory
cd "c:\Users\SamB\OneDrive - SportNZGroup\Desktop\Scripts\ME monitoring"

# Initialize git if not already done
git init

# Add all files
git add .

# Commit
git commit -m "Add GitHub Actions auto-sync for Snowflake data"

# Add your GitHub repository as remote (replace with your actual repo URL)
git remote add origin https://github.com/Bremz09/ME-monitoring.git

# Push to GitHub
git push -u origin main
```

### 2. Add Snowflake Credentials to GitHub Secrets

1. Go to your GitHub repository: https://github.com/Bremz09/ME-monitoring
2. Click **Settings** tab
3. In the left sidebar, click **Secrets and variables** → **Actions**
4. Click **New repository secret** button
5. Add each of these secrets (one at a time):

**Required Secrets:**

| Secret Name | Value |
|------------|-------|
| `SNOWFLAKE_ACCOUNT` | `URHWEIA-HPSNZ` |
| `SNOWFLAKE_USER` | `SAM.BREMER@HPSNZ.ORG.NZ` |
| `SNOWFLAKE_PASSWORD` | `your_snowflake_password` |
| `SNOWFLAKE_ROLE` | `PUBLIC` |
| `SNOWFLAKE_WAREHOUSE` | `COMPUTE_WH` |
| `SNOWFLAKE_DATABASE` | `CONSUME` |
| `SNOWFLAKE_SCHEMA` | `SMARTABASE` |

### 3. Test the GitHub Action

#### Option A: Manual Test (Recommended First)
1. Go to your repository on GitHub
2. Click the **Actions** tab
3. Click on **Sync Snowflake Data** workflow in the left sidebar
4. Click **Run workflow** dropdown button
5. Click the green **Run workflow** button
6. Wait 1-2 minutes and check if it succeeds

#### Option B: Wait for Scheduled Run
- The workflow runs automatically every hour
- First run will be at the top of the next hour (e.g., 2:00 PM, 3:00 PM, etc.)

### 4. Verify the Sync Works

After the workflow runs successfully:

1. Check your repository - you should see a new commit like:
   - `🔄 Auto-sync: Update training data from Snowflake`

2. The `data/training_peaks_data.csv` file should be updated with fresh data

3. The `data/metadata.json` file will show the last sync time

### 5. Deploy to Streamlit Cloud

Your Streamlit Cloud app will now automatically use the synced CSV file:

1. No Snowflake secrets needed in Streamlit Cloud anymore!
2. The app reads from the CSV file that GitHub Actions keeps updated
3. Data refreshes hourly without any IP whitelist issues

### 6. Remove Snowflake Secrets from Streamlit Cloud (Optional)

Since the app now uses CSV files:
1. Go to your Streamlit Cloud app settings
2. Remove the Snowflake secrets (they're not needed anymore)
3. The app will automatically use the CSV file instead

## How It Works

```
┌─────────────────┐
│  GitHub Actions │  ← Runs every hour
│   (Cloud VM)    │
└────────┬────────┘
         │
         │ 1. Connects to Snowflake
         │ 2. Pulls latest data
         │ 3. Saves to CSV
         │ 4. Commits to GitHub
         │
         ▼
┌─────────────────┐
│  GitHub Repo    │
│  (CSV file)     │
└────────┬────────┘
         │
         │ Reads data
         │
         ▼
┌─────────────────┐
│ Streamlit Cloud │  ← Your deployed app
│   (Dashboard)   │
└─────────────────┘
```

## Troubleshooting

### If the GitHub Action fails:

1. **Check the error message:**
   - Go to Actions tab → Click on the failed run → View logs

2. **Common issues:**
   - Wrong Snowflake credentials → Double-check the secrets
   - Network policy blocking GitHub IPs → Contact Snowflake admin
   - Table name changed → Update `sync_snowflake_data.py`

3. **Test locally first:**
   ```powershell
   # Set environment variables temporarily
   $env:SNOWFLAKE_ACCOUNT="URHWEIA-HPSNZ"
   $env:SNOWFLAKE_USER="SAM.BREMER@HPSNZ.ORG.NZ"
   $env:SNOWFLAKE_PASSWORD="your_password"
   $env:SNOWFLAKE_ROLE="PUBLIC"
   $env:SNOWFLAKE_WAREHOUSE="COMPUTE_WH"
   $env:SNOWFLAKE_DATABASE="CONSUME"
   $env:SNOWFLAKE_SCHEMA="SMARTABASE"
   
   # Run the sync script
   python sync_snowflake_data.py
   ```

### Change sync frequency:

Edit `.github/workflows/sync-data.yml`:

```yaml
# Every 30 minutes
- cron: '*/30 * * * *'

# Every 6 hours
- cron: '0 */6 * * *'

# Once daily at 6 AM UTC
- cron: '0 6 * * *'
```

## Benefits of This Setup

✅ **FREE** - No infrastructure costs  
✅ **Automated** - Runs without your intervention  
✅ **Reliable** - GitHub Actions has 99.9% uptime  
✅ **No IP issues** - GitHub's IPs might be whitelisted, or admin can whitelist them  
✅ **Computer off** - Works even when your PC is shut down  
✅ **Version controlled** - Data changes are tracked in git history  
✅ **Easy monitoring** - View sync status in GitHub Actions tab  

## Next Steps

After setup is complete, you can:
1. Monitor the Actions tab to see hourly syncs
2. View the commit history to see when data updates
3. Access your Streamlit app with always-fresh data
4. Forget about manual data updates! 🎉
