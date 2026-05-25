"""
schema_setup_emails.py
=======================
Creates the Emails tab with its FULL base schema.

This was the missing piece: every other migration (v1-v7) assumes the Emails
tab pre-exists and only ADDS columns to it. None of them ever CREATE it.

In the original deployment the queue writer (stage3_queue_writer.py) called
ws.append_row() before any headers existed. Google Sheets silently created
the tab and put email data in row 1 — no header row. Every subsequent
migration checked ws.row_values(1), got real email data back, assumed those
were headers, and skipped.

This migration handles all four real-world states:

  A) Tab doesn't exist at all          → create with headers
  B) Tab exists, row 1 is empty        → write headers to row 1
  C) Tab exists, row 1 looks like data → INSERT header row at top (shift down)
  D) Tab exists, row 1 has headers     → append any missing columns at end
"""

import gspread
import streamlit as st

from schema_setup import get_gspread_client, get_sheet_id


# ============================================================================
# COMPLETE EMAILS SCHEMA
# ============================================================================

EMAILS_FULL_SCHEMA = [
    # Identity & linking
    "campaign_id",
    "recipient_email",
    "idempotency_key",
    # Campaign context (denormalized for Apps Script)
    "brand",
    "vertical",
    "app_name",
    "campaign_type",
    # Variant tracking (Stage 2)
    "template_id",
    "template_version",
    "spin_path_json",
    "was_edited",
    "generated_at",
    # Email content
    "subject",
    "body",
    "html_body",
    # Sender
    "from_account",
    # Send lifecycle
    "status",
    "queued_at",
    "confirmed_at",
    "sent_at",
    "attempt_count",
    "last_attempt_at",
    "error_message",
    # Stage 5: priority + retry
    "priority_score",
    "next_retry_at",
    # Stage 7: reply tracking
    "thread_id",
    "reply_status",
]

# These are the 4 columns Apps Script requires — used to detect header vs data row
_REQUIRED_COLS = {"status", "recipient_email", "subject", "body"}


def _row_looks_like_headers(row: list) -> bool:
    """
    Return True if the row contains known column names (i.e. it's a header row).
    We check for ANY of the required column names as a reliable signal.
    """
    row_set = {str(v).strip().lower() for v in row if v}
    return bool(row_set & {c.lower() for c in _REQUIRED_COLS})


# ============================================================================
# MIGRATION
# ============================================================================

def run_emails_migration(verbose: bool = True) -> None:
    """
    Ensure the Emails tab exists and has the full schema header row.
    Handles all four states: missing tab, empty tab, data-in-row-1, headers-exist.
    Idempotent — safe to run multiple times.
    """
    if verbose:
        print("\nEmails tab base schema")
        print("-" * 40)

    gc = get_gspread_client()
    sh = gc.open_by_key(get_sheet_id())

    try:
        ws = sh.worksheet("Emails")
    except gspread.WorksheetNotFound:
        # State A: tab doesn't exist — create it fresh
        num_cols = max(30, len(EMAILS_FULL_SCHEMA) + 4)
        ws = sh.add_worksheet(title="Emails", rows=5000, cols=num_cols)
        ws.update("A1", [EMAILS_FULL_SCHEMA])
        ws.freeze(rows=1)
        ws.format("A1:AZ1", {"textFormat": {"bold": True}})
        if verbose:
            print(f"  ✓ Created Emails tab with {len(EMAILS_FULL_SCHEMA)} columns")
        return

    # Tab exists — read row 1
    row1 = ws.row_values(1)

    if not row1 or all(v == "" for v in row1):
        # State B: tab exists but row 1 is empty
        ws.update("A1", [EMAILS_FULL_SCHEMA])
        ws.freeze(rows=1)
        ws.format("A1:AZ1", {"textFormat": {"bold": True}})
        if verbose:
            print(f"  ✓ Emails tab was empty — wrote {len(EMAILS_FULL_SCHEMA)} headers")
        return

    if not _row_looks_like_headers(row1):
        # State C: row 1 has EMAIL DATA, not headers
        # Insert a blank row at position 1 to push data down, then write headers
        if verbose:
            print(f"  ⚠ Row 1 contains data (not headers) — inserting header row at top")
        ws.insert_rows([EMAILS_FULL_SCHEMA], row=1)
        ws.freeze(rows=1)
        ws.format("A1:AZ1", {"textFormat": {"bold": True}})
        if verbose:
            print(f"  ✓ Inserted {len(EMAILS_FULL_SCHEMA)}-column header row — existing data shifted to row 2+")
        return

    # State D: row 1 has real headers — check for missing columns and append
    existing_headers = [str(v).strip() for v in row1 if v]
    missing = [c for c in EMAILS_FULL_SCHEMA if c not in existing_headers]

    if not missing:
        if verbose:
            print(f"  ✓ Emails tab already has all {len(existing_headers)} required columns")
        return

    # Append missing columns after the last existing header
    next_col = len(existing_headers) + 1
    for col_name in missing:
        ws.update_cell(1, next_col, col_name)
        next_col += 1

    if verbose:
        print(f"  ✓ Added {len(missing)} missing columns: {', '.join(missing)}")


if __name__ == "__main__":
    run_emails_migration(verbose=True)
