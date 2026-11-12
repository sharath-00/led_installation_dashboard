# LED Lamp Installation Mail Dashboard

Automated **HTML Mail Dashboard generator & SMTP sender** powered directly by your Google Sheets LED lamp installation tracker (`Overall till - ...`, `... Lamp Installed`, and `Sheet2` raw lamp log tabs).

---

## 1. Share Your Google Sheet

Your service account credentials are saved in `service_account.json` (git-ignored).

1. Open your **LED Lamp Installation Google Sheet**.
2. Click **Share** (top-right) and add this service account email as **Viewer**:
   ```text
   gateway-kpi-sync@kpi-analytics-511709.iam.gserviceaccount.com
   ```
3. Open `.env` and paste your Google Sheet URL into `GOOGLE_SHEET_URL_OR_ID`.

---

## 2. Configure Email Sending (`.env`)

Fill in `.env` (already created from `.env.example`):

```env
GOOGLE_SHEET_URL_OR_ID=https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID/edit
GOOGLE_OVERALL_WORKSHEET=
GOOGLE_DAILY_WORKSHEET=
GOOGLE_RAW_WORKSHEET=

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_SENDER_NAME=LED Installation Analytics
SMTP_SENDER_EMAIL=yourname@gmail.com
SMTP_PASSWORD=your_16_char_gmail_app_password
EMAIL_RECIPIENTS=manager@company.com, ops@company.com
EMAIL_CC=
```

*(Leaving `GOOGLE_OVERALL_WORKSHEET`, `GOOGLE_DAILY_WORKSHEET`, and `GOOGLE_RAW_WORKSHEET` blank auto-detects `Overall till - ...`, latest `... Lamp Installed`, and `Sheet2` for `Installed By`, monthly trend, and 14-day trend analytics.)*
*(For Gmail, enable 2-Step Verification and generate a 16-character **App Password** under Google Account → Security → App passwords.)*

---

## 3. Run Commands

### Preview without sending mail (Dry Run)
Generates `output/latest_mail_dashboard.html` and optionally opens it in your browser:
```powershell
python send_report.py --dry-run --open
```
Or preview using the built-in sample data (no Google Sheet needed):
```powershell
python send_report.py --sample --dry-run --open
```

### Send the Mail Dashboard
```powershell
python send_report.py
```
With CSV attachments (`installer_summary.csv`, `corporation_summary.csv`, `constituency_summary.csv`, `ward_summary.csv`) and an optional note:
```powershell
python send_report.py --attach-csv --note "Daily rollout update"
```
Optional flags: `--raw-tab Sheet2` (or `--raw-tab none` to skip), `--no-top-wards`.

### Schedule Daily Automated Sends
Run continuously in background at a fixed daily time (24h format):
```powershell
python send_report.py --daily-at 19:00 --attach-csv
```
Or configure **Windows Task Scheduler** to run `python send_report.py --attach-csv` in `d:\Schnell\led_installation_dashboard`.

---

## 4. Trigger via External API Dispatch (GitHub Actions)

The workflow in `.github/workflows/send-led-report.yml` supports **external API dispatch** (`repository_dispatch` & `workflow_dispatch`), with `TZ: Asia/Kolkata` so yesterday's date resolves in IST.

### Required GitHub Repository Secrets
Add these under **GitHub Repo → Settings → Secrets and variables → Actions**:
- `GOOGLE_SERVICE_ACCOUNT_JSON` — Full JSON contents of `service_account.json`
- `GOOGLE_SHEET_URL_OR_ID` — Your Google Sheet URL or Spreadsheet ID
- `SMTP_SENDER_EMAIL` — Sender email address
- `SMTP_PASSWORD` — Gmail 16-character App Password
- `EMAIL_RECIPIENTS` — Comma-separated recipient emails

*(Optional secrets: `EMAIL_CC`, `SMTP_SENDER_NAME`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS`, `EMAIL_SUBJECT_TEMPLATE`, `GOOGLE_OVERALL_WORKSHEET`, `GOOGLE_DAILY_WORKSHEET`, `GOOGLE_RAW_WORKSHEET`.)*

### External API Call (`repository_dispatch`)
Replace `<OWNER>`, `<REPO>`, and `<GITHUB_PAT>` (a GitHub token with `repo` / `actions:write` scope):

**cURL:**
```bash
curl -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer <GITHUB_PAT>" \
  https://api.github.com/repos/<OWNER>/<REPO>/dispatches \
  -d '{"event_type":"send-led-report","client_payload":{"dry_run":false,"attach_csv":false,"note":""}}'
```

**PowerShell:**
```powershell
$headers = @{
  Accept        = "application/vnd.github+json"
  Authorization = "Bearer <GITHUB_PAT>"
}
$body = @{
  event_type     = "send-led-report"
  client_payload = @{ dry_run = $false; attach_csv = $false; note = "" }
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/<OWNER>/<REPO>/dispatches" -Headers $headers -Body $body -ContentType "application/json"
```

Supported optional `client_payload` keys: `dry_run` (`true`/`false`), `attach_csv` (`true`/`false`), `to` (recipient override), `note` (coordinator note), `sheet` (Google Sheet URL/ID override).
