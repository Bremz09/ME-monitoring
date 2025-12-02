# Snowflake IP Whitelist Request for Automation

## To: Snowflake Administrator
## From: Sam Bremer
## Re: IP Whitelist Request for Automated Dashboard Updates

---

## Problem Statement

I'm running an automated ME Monitoring dashboard that needs to pull data from Snowflake hourly. Currently, connections are blocked from cloud services due to network policy restrictions:

**Current Errors:**
- Streamlit Cloud IP: `35.197.92.111` - BLOCKED
- GitHub Actions IP: `20.55.13.163` - BLOCKED

## Request

Please whitelist IP addresses/ranges for one of these automation services:

### Option 1: GitHub Actions (Recommended - Microsoft Azure)

GitHub Actions runs on Microsoft Azure and uses these IP ranges:

**Copy this into your network policy:**
```
GitHub Actions IP ranges (updated regularly):
- Download current list: https://api.github.com/meta
- Azure region: eastus, westus, centralus, etc.
```

**Why GitHub Actions:**
- ✅ Free (2,000 minutes/month)
- ✅ Runs on Microsoft Azure infrastructure
- ✅ May already be partially whitelisted if Azure is approved
- ✅ Auditable and secure

### Option 2: Streamlit Cloud (Google Cloud Platform)

If GitHub Actions can't be whitelisted, alternative is Streamlit Community Cloud:

**Known IPs encountered:**
- `35.197.92.111`
- Additional GCP ranges may be needed

### Option 3: Specific Azure Service

If we can deploy to a specific Azure service (App Service, Container Instance, etc.), you can whitelist:
- A specific Azure datacenter region
- Or a dedicated static IP we can provision

---

## Use Case Details

**What the automation does:**
1. Connects to Snowflake every hour
2. Queries: `CONSUME.SMARTABASE.TRAINING_PEAKS_CYCLING_VW`
3. Exports data to CSV for dashboard display
4. No data modification - READ ONLY access

**Why this is needed:**
- Dashboard users need access to fresh data 24/7
- I may be unavailable for extended periods
- Manual updates are not sustainable for team access

**Security considerations:**
- Using dedicated service account credentials
- Read-only access to specific table
- All connections over HTTPS/TLS
- Credentials stored in encrypted secrets

---

## Recommended Snowflake Configuration

```sql
-- Create network policy for automation services
CREATE NETWORK POLICY automation_access
  ALLOWED_IP_LIST = (
    '35.197.92.111/32',           -- Streamlit Cloud (example)
    '20.55.13.163/32',            -- GitHub Actions (example)
    -- Add additional GitHub Actions IPs from api.github.com/meta
    -- Or add Azure/GCP CIDR ranges as approved
  )
  BLOCKED_IP_LIST = ();

-- Apply to specific user (service account)
ALTER USER SAM.BREMER@HPSNZ.ORG.NZ SET NETWORK_POLICY = automation_access;

-- Or apply account-wide (if appropriate)
-- ALTER ACCOUNT SET NETWORK_POLICY = automation_access;
```

Alternatively, if dynamic IPs are a concern:
```sql
-- Option: Whitelist entire Azure/GCP regions (broader but simpler)
-- Contact me for specific region requirements
```

---

## Alternative: VPN/Proxy Solution

If whitelisting cloud provider IPs is not feasible, we could:

1. **Set up Azure VPN Gateway** - Route traffic through HPSNZ Azure
2. **Deploy on-premise proxy** - On existing whitelisted infrastructure
3. **Use Azure Private Link** - Direct private connection to Snowflake

**Cost implications:**
- VPN Gateway: ~$25-50 USD/month
- Azure App Service with static IP: ~$70 USD/month
- On-premise proxy: Infrastructure team involvement

---

## Preferred Solution Ranking

1. **Whitelist GitHub Actions IPs** (FREE, most flexible)
2. **Whitelist Streamlit Cloud IPs** (FREE, simpler)
3. **Provision Azure static IP** (~$70/month)
4. **VPN/Proxy solution** (requires infrastructure team)

---

## Next Steps

Please advise which option is feasible within HPSNZ security policy:

- [ ] GitHub Actions IP whitelist approved
- [ ] Streamlit Cloud IP whitelist approved  
- [ ] Need to provision static IP via Azure
- [ ] Need to discuss VPN/proxy alternatives
- [ ] Not possible - manual updates only

---

## Contact Information

**Name:** Sam Bremer  
**Email:** SAM.BREMER@HPSNZ.ORG.NZ  
**Snowflake Account:** URHWEIA-HPSNZ  
**Database/Schema:** CONSUME.SMARTABASE  
**Table:** TRAINING_PEAKS_CYCLING_VW  

---

## Technical Details for Admin

**GitHub Actions IP List:**
You can get the current list programmatically:
```bash
curl https://api.github.com/meta | jq .actions
```

**Streamlit Cloud Infrastructure:**
- Platform: Google Cloud Platform
- Regions: us-central1, us-east1 (varies)
- IPs: Dynamic within GCP ranges

**Azure Static IP Option:**
If we deploy to Azure App Service/Container, we can:
1. Provision a static outbound IP
2. Provide that single IP for whitelist
3. Costs ~$70/month for Basic tier with static IP

Please let me know which path we should pursue. Happy to discuss security concerns or provide additional information.

Thank you!
