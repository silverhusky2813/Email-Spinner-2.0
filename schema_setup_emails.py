"""
schema_setup_emails.py
=======================
Creates the Emails tab with its FULL base schema.

This was the missing piece: every other migration (v1-v7) assumes the Emails
tab pre-exists and only ADDS columns to it. None of them ever CREATE it.
In a fresh Sheet, the tab never got created, so all subsequent migrations
silently skipped it with "Emails tab not found" warnings.

This migration:
  1. Creates the Emails tab with ALL columns the system needs (idempotent)
  2. Writes the header row if missing
  3. Is safe to run on an existing Emails tab — skips if headers look complete

Run order: this must run BEFORE schema_setup.py (v1).
migrate_all.py has been updated to run it as step 0.
"""

import gspread
import streamlit as st

from schema_setup import get_gspread_client, get_sheet_id


# ============================================================================
# COMPLETE EMAILS SCHEMA (all stages combined)
# ============================================================================
#
# Column groups — commented to show which migration originally added each:
#
#   BASE    : columns the system was always assumed to have
#   v1      : campaign_id (originally inserted at col A, now part of base)
#   v2      : variant tracking
#   v3      : html body, sender, idempotency, retry infrastructure
#   v4/5    : priority, scheduling, thread_id, reply tracking
#
# IMPORTANT: column ORDER here is the canonical order for the Emails tab.
# Never insert mid-schema — only append. Apps Script reads by header name,
# not position, so order doesn't affect script behaviour.

EMAILS_FULL_SCHEMA = [
    # --- Identity & linking ---
    "campaign_id",          # A  UUID linking to Campaigns tab
    "recipient_email",      # B  normalized lowercase
    "idempotency_key",      # C  sha256(campaign_id|recipient_email)[:16]

    # --- Campaign context (denormalized for Apps Script convenience) ---
    "brand",                # D
    "vertical",             # E
    "app_name",             # F
    "campaign_type",        # G  Outreach | Brief | FollowUp | WinBack

    # --- Variant tracking (Stage 2) ---
    "template_id",          # H
    "template_version",     # I
    "spin_path_json",       # J  JSON blob of which text was chosen at each spin
    "was_edited",           # K  TRUE | FALSE
    "generated_at",         # L  ISO timestamp

    # --- Email content ---
    "subject",              # M  plain text subject line
    "body",                 # N  plain text body
    "html_body",            # O  HTML-rendered body (Stage 3)

    # --- Sender ---
    "from_account",         # P  e.g. daniel@premiumads.net

    # --- Send lifecycle ---
    "status",               # Q  Queued | Sending | Sent | Failed | Bounced | Delivered
    "queued_at",            # R  ISO timestamp
    "confirmed_at",         # S  when user clicked Confirm in Stage 3
    "sent_at",              # T  set by Apps Script on success
    "attempt_count",        # U  0 = never tried
    "last_attempt_at",      # V  last Apps Script attempt
    "error_message",        # W  last error, if status=Failed

    # --- Stage 5: priority + retry scheduling ---
    "priority_score",       # X  tier_weight × 1e12 − queued_epoch
    "next_retry_at",        # Y  ISO — empty = eligible now

    # --- Stage 7: reply tracking ---
    "thread_id",            # Z  Gmail thread ID (captured at send via draft→send)
    "reply_status",         # AA none | genuine | auto_reply | bounce | unsubscribe
]


# ============================================================================
# MIGRATION
# ============================================================================

def run_emails_migration(verbose: bool = True) -> None:
    """
    Ensure the Emails tab exists and has the full schema header row.
    Idempotent — safe to run multiple times.
    """
    if verbose:
        print("\nEmails tab base schema")
        print("-" * 40)

    gc = get_gspread_client()
    sh = gc.open_by_key(get_sheet_id())

    try:
        ws = sh.worksheet("Emails")
        existing_headers = ws.row_values(1)

        if not existing_headers:
            # Tab exists but empty (e.g., manually created) — write headers
            ws.update("A1", [EMAILS_FULL_SCHEMA])
            ws.freeze(rows=1)
            ws.format("A1:AZ1", {"textFormat": {"bold": True}})
            if verbose:
                print(f"  ✓ Emails tab existed empty — wrote {len(EMAILS_FULL_SCHEMA)} headers")
            return

        # Tab exists with headers — add any missing columns at the end
        missing = [c for c in EMAILS_FULL_SCHEMA if c not in existing_headers]
        if not missing:
            if verbose:
                print(f"  ✓ Emails tab already has all {len(existing_headers)} required columns")
            return

        # Append missing columns only (never insert mid-schema)
        for col_name in missing:
            # Append header in next available column
            next_col = len(existing_headers) + 1
            ws.update_cell(1, next_col, col_name)
            existing_headers.append(col_name)

        if verbose:
            print(f"  ✓ Added {len(missing)} missing columns: {', '.join(missing)}")

    except gspread.WorksheetNotFound:
        # Create from scratch
        num_cols = max(26, len(EMAILS_FULL_SCHEMA) + 4)
        ws = sh.add_worksheet(title="Emails", rows=5000, cols=num_cols)
        ws.update("A1", [EMAILS_FULL_SCHEMA])
        ws.freeze(rows=1)
        ws.format("A1:AZ1", {"textFormat": {"bold": True}})
        if verbose:
            print(f"  ✓ Created Emails tab with {len(EMAILS_FULL_SCHEMA)} columns")


if __name__ == "__main__":
    run_emails_migration(verbose=True)
