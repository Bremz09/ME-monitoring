# Automated Data Updates - All Options

## Current Situation

Your ME Monitoring dashboard needs fresh data from Snowflake, but Snowflake's network policy blocks connections from cloud automation services (GitHub Actions, Streamlit Cloud).

---

## ✅ SOLUTION OPTIONS (Ranked by Automation Level)

### 🏆 Option 1: Get IP Whitelist Approved (BEST - Fully Automated)

**How it works:**
- Ask Snowflake admin to whitelist GitHub Actions IPs
- Workflow runs automatically every hour/day
- Zero manual intervention needed
- Works even when you're away for weeks

**Steps:**
1. Send `SNOWFLAKE_IP_WHITELIST_REQUEST.md` to your Snowflake admin
2. Once approved, GitHub Actions will work automatically
3. Data updates every hour (or whatever schedule you set)

**Pros:**
- ✅ Fully automated - works while you're away
- ✅ FREE
- ✅ Zero maintenance after setup

**Cons:**
- ⏳ Requires admin approval (may take time)
- 🔒 May face security policy resistance

---

### 🥈 Option 2: Azure App Service with Static IP (~$70/month)

**How it works:**
- Deploy your app to Azure App Service (Basic tier or higher)
- Get a dedicated static outbound IP
- Admin whitelists this one IP
- App connects to Snowflake directly

**Steps:**
1. Deploy to Azure App Service (Basic B1 tier minimum)
2. Get the outbound IP address from Azure portal
3. Admin whitelists this single IP
4. App runs 24/7 with direct Snowflake connection

**Pros:**
- ✅ Fully automated - works while you're away
- ✅ Static IP easier to whitelist than dynamic ranges
- ✅ Professional infrastructure
- ✅ On Azure (might already have partial access to HPSNZ network)

**Cons:**
- 💰 Costs ~$70 USD/month
- 🔧 Requires Azure deployment setup

**Cost breakdown:**
- Basic B1 App Service: ~$13/month
- Basic Load Balancer (for static IP): ~$18/month
- Or Standard S1 tier (includes static IP): ~$70/month

---

### 🥉 Option 3: Scheduled Task on Work Computer (FREE but requires computer)

**How it works:**
- Windows Task Scheduler runs sync script daily
- Your work computer must be on and connected
- Automatically pushes to GitHub
- Streamlit reads from GitHub

**Steps:**
1. Set up Windows Task Scheduler
2. Schedule `quick_update.bat` to run daily (e.g., 6 AM)
3. Keep work computer on or set wake timers

**Pros:**
- ✅ FREE
- ✅ Uses whitelisted connection
- ✅ Simple setup

**Cons:**
- ⚠️ Computer must be on
- ⚠️ Breaks when you're away
- ⚠️ Not truly "hands-off"

---

### Option 4: Manual Updates (FREE, most manual)

**How it works:**
- Double-click `quick_update.bat` when you want fresh data
- Or someone else on your team does it

**Pros:**
- ✅ FREE
- ✅ Full control over updates
- ✅ Works immediately

**Cons:**
- ❌ Requires manual action
- ❌ No updates when everyone is away
- ❌ Not sustainable long-term

---

## 📊 Comparison Table

| Option | Cost | Automation | Works When Away | Setup Time |
|--------|------|------------|-----------------|------------|
| **IP Whitelist** | FREE | 100% | ✅ Yes | 1 hour + admin approval |
| **Azure Static IP** | $70/mo | 100% | ✅ Yes | 2-3 hours |
| **Scheduled Task** | FREE | 90% | ❌ No (needs PC on) | 30 mins |
| **Manual Updates** | FREE | 0% | ❌ No | 5 mins |

---

## 💡 Recommended Approach

### For You (Sam):

**Immediate (this week):**
1. Send IP whitelist request to Snowflake admin (`SNOWFLAKE_IP_WHITELIST_REQUEST.md`)
2. While waiting, use manual updates or scheduled task

**If admin approves (ideal):**
- GitHub Actions works automatically
- FREE and fully automated
- Done! 🎉

**If admin denies (alternative):**
- Request budget approval for Azure deployment (~$70/month)
- Or accept that data updates require computer to be on

---

## 🚀 Quick Start Guide

### For IP Whitelist Approach:

1. **Send request:**
   ```
   Email SNOWFLAKE_IP_WHITELIST_REQUEST.md to Snowflake admin
   ```

2. **Add GitHub Secrets** (if approved):
   - Go to: https://github.com/Bremz09/ME-monitoring/settings/secrets/actions
   - Add:
     - `SNOWFLAKE_ACCOUNT`: `URHWEIA-HPSNZ`
     - `SNOWFLAKE_USER`: `SAM.BREMER@HPSNZ.ORG.NZ`
     - `SNOWFLAKE_PASSWORD`: (your password)
     - `SNOWFLAKE_ROLE`: `PUBLIC`
     - `SNOWFLAKE_WAREHOUSE`: `COMPUTE_WH`
     - `SNOWFLAKE_DATABASE`: `CONSUME`
     - `SNOWFLAKE_SCHEMA`: `SMARTABASE`

3. **Test the workflow:**
   - Go to Actions tab on GitHub
   - Run "Daily Training Peaks Data Extraction" manually
   - Check if it succeeds

4. **Done!** It will run automatically after that.

---

### For Azure Deployment:

1. **Create Azure App Service:**
   ```bash
   az webapp create --resource-group <your-rg> --plan <plan-name> --name me-monitoring --runtime "PYTHON:3.11"
   ```

2. **Get outbound IP:**
   ```bash
   az webapp show --resource-group <your-rg> --name me-monitoring --query outboundIpAddresses
   ```

3. **Send IP to Snowflake admin for whitelisting**

4. **Deploy your app:**
   - Configure Snowflake credentials in Azure App Settings
   - Deploy code via GitHub Actions or Azure CLI

---

## 🔍 Current Status

- ✅ App code ready (works with CSV or Snowflake)
- ✅ GitHub Actions workflow configured
- ❌ GitHub Actions blocked by Snowflake network policy
- ❌ Streamlit Cloud blocked by Snowflake network policy
- ✅ Local computer CAN connect (whitelisted)

**Next action needed:** Choose automation option above and proceed with setup.

---

## 📞 Need Help?

**For IP whitelist:** Use `SNOWFLAKE_IP_WHITELIST_REQUEST.md`  
**For Azure setup:** I can provide detailed deployment guide  
**For scheduled tasks:** I can create Windows Task Scheduler config  

The IP whitelist approval is the best path forward for true hands-off automation.
