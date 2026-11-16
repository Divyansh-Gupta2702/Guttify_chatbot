#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${MAIL_REPORT_ENV_FILE:-$SCRIPT_DIR/customer-symptoms-mail.env}"
LOG_FILE="${MAIL_REPORT_LOG:-$SCRIPT_DIR/customer-symptoms-mail.log}"
CRON_MARKER="# gutgpt-customer-symptoms-mail"
CRON_TZ_MARKER="# gutgpt-customer-symptoms-mail-timezone"

if [[ -f "$ENV_FILE" ]]; then
  # This is an operator-managed, trusted shell config file. Keep credentials out
  # of the script and do not commit the .env file.
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ "${1:-}" == "--install" ]]; then
  command -v crontab >/dev/null || { echo "crontab is required to install the hourly schedule." >&2; exit 1; }
  [[ -f "$ENV_FILE" ]] || { echo "Create $ENV_FILE from customer-symptoms-mail.env.example first." >&2; exit 1; }
  script_path="$(realpath "$0")"
  env_path="$(realpath "$ENV_FILE")"
  log_path="$(realpath -m "$LOG_FILE")"
  printf -v quoted_script '%q' "$script_path"
  printf -v quoted_env '%q' "$env_path"
  printf -v quoted_log '%q' "$log_path"
  tmp_crontab="$(mktemp)"
  trap 'rm -f -- "$tmp_crontab"' EXIT
  (crontab -l 2>/dev/null || true) | awk -v marker="$CRON_MARKER" -v tz_marker="$CRON_TZ_MARKER" \
    '$0 == tz_marker { skip_next=1; next } index($0, marker) { next } skip_next { skip_next=0; next } { print }' >"$tmp_crontab"
  printf '%s\nCRON_TZ=Asia/Kolkata\n' "$CRON_TZ_MARKER" >>"$tmp_crontab"
  printf '0 10-19 * * * MAIL_REPORT_ENV_FILE=%s MAIL_REPORT_LOG=%s %s >> %s 2>&1 %s\n' \
    "$quoted_env" "$quoted_log" "$quoted_script" "$quoted_log" "$CRON_MARKER" >>"$tmp_crontab"
  crontab "$tmp_crontab"
  echo "Installed hourly customer symptom email schedule (10:00–19:00 Asia/Kolkata)."
  exit 0
fi

required=(GUTGPT_ADMIN_API_URL GUTGPT_ADMIN_TOKEN MAIL_REPORT_TO MAIL_REPORT_FROM SMTP_HOST)
for key in "${required[@]}"; do
  if [[ -z "${!key:-}" ]]; then
    echo "Required setting is missing: $key (configure it in $ENV_FILE or the environment)." >&2
    exit 1
  fi
done

export GUTGPT_ADMIN_API_URL GUTGPT_ADMIN_TOKEN MAIL_REPORT_TO MAIL_REPORT_FROM
export SMTP_HOST SMTP_PORT SMTP_USERNAME SMTP_PASSWORD SMTP_USE_STARTTLS
python3 - <<'PY'
import html
import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Required setting is missing: {name}")
    return value


api_url = required("GUTGPT_ADMIN_API_URL").rstrip("/")
token = required("GUTGPT_ADMIN_TOKEN")
recipients = [part.strip() for part in required("MAIL_REPORT_TO").split(",") if part.strip()]
sender = required("MAIL_REPORT_FROM")
request = Request(api_url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
try:
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
except HTTPError as exc:
    raise RuntimeError(f"Customer API returned HTTP {exc.code}") from exc
except URLError as exc:
    raise RuntimeError(f"Could not reach customer API: {exc.reason}") from exc

customers = payload.get("customers") if isinstance(payload, dict) else None
if not isinstance(customers, list):
    raise RuntimeError("Customer API response did not include a customers list")

ist = timezone(timedelta(hours=5, minutes=30))
window_end = datetime.now(ist).replace(minute=0, second=0, microsecond=0)
# There are no scheduled reports between 19:00 and 10:00, so the 10:00
# report covers that full overnight gap. All other reports cover one hour.
window_start = window_end - timedelta(hours=15 if window_end.hour == 10 else 1)


def parse_timestamp(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ist)
    return parsed.astimezone(ist)


def latest_assessment(customer):
    assessments = customer.get("assessments")
    if not isinstance(assessments, list):
        return None
    dated = [(parse_timestamp(item.get("started_at")), item)
             for item in assessments if isinstance(item, dict)]
    dated = [(stamp, item) for stamp, item in dated if stamp is not None]
    return max(dated, key=lambda pair: pair[0])[1] if dated else None


# A report at 11:00 covers [10:00, 11:00). Registration and each new
# assessment are qualifying events; the timestamp window prevents either
# event from recurring in later hourly reports.
eligible_customers = []
for customer in customers:
    if not isinstance(customer, dict):
        continue
    assessment = latest_assessment(customer)
    registration_time = parse_timestamp(customer.get("created_at"))
    assessment_time = parse_timestamp(assessment.get("started_at")) if assessment else None
    registered_in_window = registration_time is not None and window_start <= registration_time < window_end
    assessed_in_window = assessment_time is not None and window_start <= assessment_time < window_end
    if not (registered_in_window or assessed_in_window):
        continue
    customer = dict(customer)
    customer["assessment_symptoms"] = (
        assessment.get("assessment_symptoms") if assessment
        else customer.get("assessment_symptoms")
    ) or ""
    eligible_customers.append(customer)

if not eligible_customers:
    print(f"No qualifying customers for {window_start:%d %b %Y %H:%M}–{window_end:%H:%M} IST; email not sent.")
    raise SystemExit(0)

fields = ("name", "age", "contact", "location", "assessment_symptoms")
labels = ("Name", "Age", "Contact", "Location", "Latest symptoms")
plain_rows = []
html_rows = []
for customer in eligible_customers:
    values = [str(customer.get(field) or "") for field in fields]
    values[-1] = values[-1] or "No symptom summary available"
    plain_rows.append("\n".join(f"{label}: {value}" for label, value in zip(labels, values)))
    html_rows.append("<tr>" + "".join(f"<td>{html.escape(value)}</td>" for value in values) + "</tr>")

window_label = f"{window_start:%d %b %Y %H:%M}–{window_end:%H:%M} IST"
subject = f"GutGPT customer symptoms: {window_label} ({len(eligible_customers)} customers)"
message = EmailMessage()
message["Subject"] = subject
message["From"] = sender
message["To"] = ", ".join(recipients)
message.set_content(
    f"GutGPT customer symptom report for {window_label}\n\n" +
    ("\n\n".join(plain_rows) if plain_rows else "No customer records found.")
)
message.add_alternative(
    f"<html><body><h2>GutGPT customer symptom report</h2><p>{html.escape(window_label)}</p>"
    "<table border='1' cellpadding='6' cellspacing='0'><thead><tr>" +
    "".join(f"<th>{html.escape(label)}</th>" for label in labels) +
    "</tr></thead><tbody>" +
    ("".join(html_rows) if html_rows else "<tr><td colspan='5'>No customer records found.</td></tr>") +
    "</tbody></table></body></html>",
    subtype="html",
)

host = required("SMTP_HOST")
port = int(os.environ.get("SMTP_PORT", "587"))
username = os.environ.get("SMTP_USERNAME", "").strip()
password = os.environ.get("SMTP_PASSWORD", "")
use_starttls = os.environ.get("SMTP_USE_STARTTLS", "true").strip().lower() in {"1", "true", "yes", "on"}
context = ssl.create_default_context()
if port == 465:
    with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as server:
        if username:
            server.login(username, password)
        server.send_message(message)
else:
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.ehlo()
        if use_starttls:
            server.starttls(context=context)
            server.ehlo()
        if username:
            server.login(username, password)
        server.send_message(message)
print(f"Sent customer symptom report to {len(recipients)} recipient(s).")
PY
