@echo off
REM Windows Task Scheduler - Daily Data Extraction
REM This runs your existing extract_data.py script automatically

echo ======================================================
echo Daily Training Peaks Data Extraction
echo Started at %date% %time%
echo ======================================================

REM Change to the script directory
cd /d "c:\Users\SamB\OneDrive - SportNZGroup\Desktop\Scripts\ME monitoring"

REM Verify we're in a git repository
git status >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ⚠️ Warning: Not in a git repository or git not available
    echo Data extraction will continue but won't sync to GitHub
)

REM Run the data extraction (uses your Azure AD authentication)
echo 🔄 Running data extraction...
python extract_data.py

REM Check if extraction was successful
if %ERRORLEVEL% EQU 0 (
    echo ✅ Data extraction completed successfully
    
    REM Git commit and sync to GitHub
    echo.
    echo 📤 Syncing data to GitHub repository...
    
    REM Add all data files
    git add data/
    
    REM Check if there are changes to commit
    git diff --staged --quiet
    if %ERRORLEVEL% NEQ 0 (
        REM There are changes, commit them
        git commit -m "Automated daily data update - %date% %time%"
        if %ERRORLEVEL% EQU 0 (
            echo ✅ Changes committed to local repository
            
            REM Push to GitHub
            git push origin main
            if %ERRORLEVEL% EQU 0 (
                echo ✅ Data successfully synced to GitHub
            ) else (
                echo ⚠️ Failed to push to GitHub - check internet connection
            )
        ) else (
            echo ⚠️ Failed to commit changes locally
        )
    ) else (
        echo ℹ️ No new data changes to commit
    )
) else (
    echo ❌ Data extraction failed - skipping GitHub sync
)

echo ======================================================
echo Daily extraction completed at %date% %time%
echo ======================================================