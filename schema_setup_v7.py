"""
schema_setup_v7.py
====================
BUGFIX migration. Adds the `recipient_email` column to the Campaigns tab.

THE BUG (caught in production):
  Stage 1 collected recipient_email and passed it to save_campaign(), but
  CAMPAIGNS_SCHEMA never included the column — so save_campaign() silently
  dropped it. Campaign rows were written with no recipient. Stage 2 then read
  the campaign back, found no recipient_email, and errored:
    "Campaign has no recipient_email. This shouldn't happen after Stage 1."

THE FIX:
  1. CAMPAIGNS_SCHEMA now includes target_geo (col Q, from v2) and
     recipient_email (col R, this migration) — appended at the END so existing
     column positions don't shift.
  2. This migration physically adds the recipient_email column to the sheet.
  3. Best-effort backfill: for existing campaigns missing a recipient, pull it
     from the most recent matching Emails row if one exists.

Run AFTER schema_setup_v6.py (it's last because it was added last).
Idempotent — safe to re-run.
"""

from datetime import datetime

import gspread

from schema_setup import get_gspread_client, get_sheet_id
from schema_setup_v2 import add_columns_if_missing


CAMPAIGNS_V7_NEW_COLUMNS = [
    "recipient_email",   # R  — was missing; the bug this migration fixes
]


def run_migration_v7(verbose: bool = True):
    """Add recipient_email to Campaigns tab + backfill. Idempotent."""
    if verbose:
        print(f"\n{'='*60}")
        print(f"Stage 1 BUGFIX Migration (v7) — {datetime.now().isoformat()}")
        print(f"{'='*60}\n")

    gc = get_gspread_client()
    sheet_id = get_sheet_id()
    sh = gc.open_by_key(sheet_id)

    if verbose:
        print(f"Opened spreadsheet: {sh.title}\n")

    # Step 1: ensure target_geo exists (v2 should have added it, but be safe —
    # CAMPAIGNS_SCHEMA now expects it at column Q before recipient_email at R)
    print("Step 1/3: Ensure target_geo column exists on Campaigns")
    try:
        campaigns_ws = sh.worksheet("Campaigns")
    except gspread.WorksheetNotFound:
        print("  ⚠ Campaigns tab not found — run schema_setup.py first")
        return
    added_geo = add_columns_if_missing(campaigns_ws, ["target_geo"])
    if not added_geo:
        print("  ✓ target_geo already present")

    # Step 2: add recipient_email column
    print("\nStep 2/3: Add recipient_email column to Campaigns")
    added = add_columns_if_missing(campaigns_ws, CAMPAIGNS_V7_NEW_COLUMNS)
    if not added:
        print("  ✓ recipient_email already present")

    # Step 3: backfill recipient_email for existing campaigns from Emails tab
    print("\nStep 3/3: Backfill recipient_email for existing campaigns")
    _backfill_recipients(sh, campaigns_ws)

    if verbose:
        print(f"\n{'='*60}")
        print("v7 bugfix migration complete!")
        print(f"{'='*60}\n")


def _backfill_recipients(sh, campaigns_ws):
    """
    For campaigns missing recipient_email, try to recover it from the most
    recent Emails row with the same campaign_id.
    """
    try:
        emails_ws = sh.worksheet("Emails")
    except gspread.WorksheetNotFound:
        print("  (no Emails tab — nothing to backfill from)")
        return

    campaign_records = campaigns_ws.get_all_records()
    email_records = emails_ws.get_all_records()
    headers = campaigns_ws.row_values(1)

    if "recipient_email" not in headers:
        print("  ⚠ recipient_email column missing after add — aborting backfill")
        return
    recipient_col = headers.index("recipient_email") + 1

    # Build campaign_id → recipient_email lookup from Emails (most recent wins)
    email_recipient = {}
    for er in email_records:
        cid = er.get("campaign_id", "")
        rec = er.get("recipient_email", "")
        if cid and rec:
            email_recipient[cid] = rec  # last one wins (good enough)

    backfilled = 0
    for i, cr in enumerate(campaign_records):
        row_num = i + 2  # +1 header, +1 for 1-index
        existing = str(cr.get("recipient_email", "")).strip()
        if existing:
            continue  # already has one
        cid = cr.get("campaign_id", "")
        recovered = email_recipient.get(cid, "")
        if recovered:
            campaigns_ws.update_cell(row_num, recipient_col, recovered)
            backfilled += 1

    if backfilled:
        print(f"  ✓ Backfilled {backfilled} campaign(s) from Emails history")
    else:
        print("  ✓ No campaigns needed backfill (or none recoverable)")
        print("    Note: campaigns with no recipient and no Emails row can't be")
        print("    recovered — just create a fresh campaign for those.")


if __name__ == "__main__":
    run_migration_v7()
