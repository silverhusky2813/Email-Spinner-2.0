"""
app.py
=======
PremiumAds Spintax Tool — unified entry point.

Wires all stages into one workflow with sidebar navigation and session-state
routing. This is the single file you run:

    streamlit run app.py

────────────────────────────────────────────────────────────────────────────
THE WORKFLOW (linear send flow + standalone monitoring screens)
────────────────────────────────────────────────────────────────────────────

  SEND FLOW (sequential):
    Stage 1  Campaign setup ──▶ Stage 2  Generate variant ──▶ Stage 3  Confirm & queue

  MONITORING (standalone, reachable any time via sidebar):
    Queue        — all queued/sent/failed rows (Stage 4 view)
    Dashboard    — operational health: throughput, drain time (Stage 5)
    Analytics    — variant reply-rate performance (Stage 7)
    Accounts     — sender health, warm-up, auto-pause (Stage 6)

Routing is driven by st.session_state["active_view"]. Each stage returns a
"next action" string; the router translates that into a view transition.
────────────────────────────────────────────────────────────────────────────
"""

import streamlit as st

# ---- Stage UIs ----
from stage1_ui import render_stage1, ensure_user_identified
from stage2_ui import render_stage2
from stage3_ui import render_stage3
from stage4_queue_view import render_queue_view
from stage5_dashboard_ui import render_dashboard
from stage6_accounts_ui import render_accounts
from stage7_analytics_ui import render_analytics
from setup_gate import ensure_schema_ready
from sheet_cache import SheetCache


# ============================================================================
# PAGE CONFIG
# ============================================================================

st.set_page_config(
    page_title="PremiumAds Spintax Tool",
    page_icon="📧",
    layout="wide",
)


# ============================================================================
# SESSION STATE HELPERS
# ============================================================================

def _get_view() -> str:
    """Current active view. Defaults to the start of the send flow."""
    return st.session_state.get("active_view", "stage1")


def _go(view: str):
    """Transition to a view and rerun."""
    st.session_state["active_view"] = view
    st.rerun()


def _reset_to_new_campaign():
    """Clear all flow state and return to Stage 1 fresh."""
    for key in [
        "active_view", "current_campaign_id", "current_approved",
    ]:
        st.session_state.pop(key, None)
    # Clear any per-campaign stage2/stage3 keys
    for key in list(st.session_state.keys()):
        if key.startswith("stage2_") or key.startswith("stage3_"):
            st.session_state.pop(key, None)
    st.rerun()


def _clear_recipient_state():
    """
    Clear recipient-specific state but KEEP the campaign — used for
    'back to stage 2' (re-pick a variant for the SAME recipient).
    """
    st.session_state.pop("current_approved", None)
    for key in list(st.session_state.keys()):
        if key.startswith("stage2_") or key.startswith("stage3_"):
            st.session_state.pop(key, None)


def _clear_send_flow_state():
    """
    Clear campaign + recipient + variant state, returning to a clean Stage 1,
    but PRESERVE user identity (don't re-prompt 'who are you'). Used by
    'send another to this campaign' — each send is a new (campaign, recipient)
    pair, and Stage 1's 'Load from recent' makes reusing settings fast.
    """
    for key in ["active_view", "current_campaign_id", "current_approved"]:
        st.session_state.pop(key, None)
    for key in list(st.session_state.keys()):
        if key.startswith("stage2_") or key.startswith("stage3_"):
            st.session_state.pop(key, None)


# ============================================================================
# SIDEBAR NAVIGATION
# ============================================================================

def _render_sidebar():
    with st.sidebar:
        st.title("📧 PremiumAds")
        st.caption("Spintax outreach engine")

        # User identity (set by ensure_user_identified)
        user = st.session_state.get("user_email")
        if user:
            st.caption(f"👤 {user}")

        st.divider()

        # --- Send flow ---
        st.caption("**SEND FLOW**")
        if st.button("➕ New campaign", use_container_width=True):
            _reset_to_new_campaign()

        # Show current position in the flow
        view = _get_view()
        flow_label = {
            "stage1": "① Campaign setup",
            "stage2": "② Generate variant",
            "stage3": "③ Confirm & queue",
        }.get(view)
        if flow_label:
            st.caption(f"Current: {flow_label}")

        st.divider()

        # --- Monitoring ---
        st.caption("**MONITORING**")
        if st.button("📋 Queue", use_container_width=True):
            _go("queue")
        if st.button("📊 Health dashboard", use_container_width=True):
            _go("dashboard")
        if st.button("📈 Analytics", use_container_width=True):
            _go("analytics")
        if st.button("✉️ Accounts", use_container_width=True):
            _go("accounts")

        st.divider()

        # --- Admin ---
        st.caption("**ADMIN**")
        if st.button("⚙️ Maintenance", use_container_width=True):
            _go("maintenance")

        st.divider()
        st.caption("v1.0 · 7-stage pipeline")


# ============================================================================
# VIEW ROUTER
# ============================================================================

def _route():
    view = _get_view()

    # ---- SEND FLOW ----

    if view == "stage1":
        campaign_id = render_stage1()
        if campaign_id:
            st.session_state["current_campaign_id"] = campaign_id
            _go("stage2")

    elif view == "stage2":
        campaign_id = st.session_state.get("current_campaign_id")
        if not campaign_id:
            _go("stage1")
            return  # _go raises rerun, but be explicit — never call render with None
        approved = render_stage2(campaign_id)
        if approved:
            st.session_state["current_approved"] = approved
            _go("stage3")

    elif view == "stage3":
        approved = st.session_state.get("current_approved")
        if not approved:
            _go("stage2")
            return  # never call render_stage3(None)
        action = render_stage3(approved)
        if action == "send_another":
            # BUG FIX: "send another" must return to Stage 1, not Stage 2.
            # The recipient_email lives on the campaign row (set in Stage 1);
            # Stage 2 reads it from there and has no recipient input. Looping
            # to Stage 2 would re-target the SAME recipient (then get blocked by
            # the idempotency check). Stage 1 is where a new recipient is
            # entered — and its "Load from recent campaign" feature makes
            # reusing the brand/vertical/CPM fast. We clear the campaign id so
            # Stage 1 starts a fresh (campaign, recipient) pair.
            _clear_send_flow_state()
            _go("stage1")
        elif action == "new_campaign":
            _reset_to_new_campaign()
        elif action == "view_queue":
            _go("queue")
        elif action == "back_to_stage2":
            # Genuine "go back and re-pick a variant for the SAME recipient"
            _clear_recipient_state()
            _go("stage2")

    # ---- MONITORING SCREENS ----

    elif view == "queue":
        action = render_queue_view()
        if action == "new_campaign":
            _reset_to_new_campaign()

    elif view == "dashboard":
        action = render_dashboard()
        if action == "new_campaign":
            _reset_to_new_campaign()
        elif action == "view_queue":
            _go("queue")

    elif view == "analytics":
        action = render_analytics()
        if action == "new_campaign":
            _reset_to_new_campaign()
        elif action == "dashboard":
            _go("dashboard")

    elif view == "accounts":
        action = render_accounts()
        if action == "new_campaign":
            _reset_to_new_campaign()
        elif action == "dashboard":
            _go("dashboard")
        elif action == "analytics":
            _go("analytics")

    elif view == "maintenance":
        _render_maintenance()

    else:
        # Unknown view — reset
        _go("stage1")



# ============================================================================
# MAINTENANCE VIEW
# ============================================================================

def _render_maintenance():
    """Admin panel: run migrations, clear cache, inspect Sheet schema."""
    st.title("⚙️ Maintenance")
    st.caption(
        "Run schema migrations and cache operations without needing terminal access. "
        "All migrations are idempotent — safe to run multiple times."
    )

    # ── Section 1: Schema migrations ──────────────────────────────────────
    st.subheader("📐 Schema Migrations")
    st.markdown(
        "Runs the full migration chain in order (v0→v7). "
        "Adds any missing tabs and columns — never deletes or shifts existing data."
    )

    col1, col2 = st.columns([2, 1])
    with col1:
        verbose = st.checkbox("Show detailed output", value=True)
    with col2:
        run_btn = st.button("🚀 Run all migrations", type="primary", use_container_width=True)

    if run_btn:
        output_lines = []
        import io, sys

        # Capture stdout from the migration runner
        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        try:
            from migrate_all import run_all_migrations
            run_all_migrations(verbose=verbose)
            output = buf.getvalue()
            SheetCache.invalidate_all()
            sys.stdout = old_stdout
            st.success("✅ All migrations complete. Sheet cache cleared.")
            if verbose and output:
                st.code(output, language="text")
        except Exception as e:
            output = buf.getvalue()
            sys.stdout = old_stdout
            st.error(f"❌ Migration failed: {type(e).__name__}: {e}")
            if output:
                st.code(output, language="text")

    st.divider()

    # ── Section 2: Run individual migration ───────────────────────────────
    st.subheader("🔧 Run Single Migration")

    migration_map = {
        "v0 — Emails base schema (CREATE tab + all headers)": "schema_setup_emails",
        "v1 — Campaigns, Presets, Suppression tabs":          "schema_setup",
        "v2 — Publishers, cpm_rates, variant columns":        "schema_setup_v2",
        "v3 — HTML body, sender, idempotency, retries":       "schema_setup_v3",
        "v4 — sender_accounts, send_log, priority":           "schema_setup_v4",
        "v5 — Reply tracking, reply_log, thread_id":          "schema_setup_v5",
        "v6 — Warm-up, pause columns, health log":            "schema_setup_v6",
        "v7 — recipient_email on Campaigns (bugfix)":         "schema_setup_v7",
    }

    selected = st.selectbox("Select migration to run:", list(migration_map.keys()))
    if st.button("▶️ Run selected migration", use_container_width=False):
        module_name = migration_map[selected]
        import io, sys, importlib
        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        try:
            mod = importlib.import_module(module_name)
            # Each module exposes either run_migration, run_migration_vN, or run_emails_migration
            fn = getattr(mod, "run_migration", None) or \
                 getattr(mod, "run_emails_migration", None) or \
                 next((getattr(mod, a) for a in dir(mod) if a.startswith("run_migration")), None)
            if fn:
                fn(verbose=True)
                output = buf.getvalue()
                SheetCache.invalidate_all()
                sys.stdout = old_stdout
                st.success(f"✅ {selected.split('—')[0].strip()} complete.")
                if output:
                    st.code(output, language="text")
            else:
                sys.stdout = old_stdout
                st.error(f"No run function found in {module_name}")
        except Exception as e:
            output = buf.getvalue()
            sys.stdout = old_stdout
            st.error(f"❌ {type(e).__name__}: {e}")
            if output:
                st.code(output, language="text")

    st.divider()

    # ── Section 3: Cache management ────────────────────────────────────────
    st.subheader("🗄️ Cache Management")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧹 Clear all cached Sheet data", use_container_width=True):
            SheetCache.invalidate_all()
            st.success("Cache cleared — next read will fetch fresh from Sheets.")
    with col2:
        # Show current cache state
        cache_keys = [k for k in st.session_state.keys() if k.startswith("__sc_")]
        if cache_keys:
            import time
            ages = []
            for k in cache_keys:
                tab = k.replace("__sc_", "")
                entry = st.session_state[k]
                age = int(time.time() - entry["ts"])
                ages.append(f"**{tab}**: {age}s old ({len(entry['data'])} rows)")
            st.caption("Cached tabs:\n" + "\n".join(ages))
        else:
            st.caption("No tabs currently cached.")

    st.divider()

    # ── Section 4: Orphaned row cleanup ───────────────────────────────────
    st.subheader("🧹 Clean Up Orphaned Email Rows")
    st.markdown(
        "Removes rows in the Emails tab that have **no status and no subject** "
        "(written by interrupted sessions before the header row existed). "
        "Rows with a real status (`Queued`, `Sent`, `Failed`) are never touched."
    )

    if st.button("🗑️ Delete orphaned rows", use_container_width=False):
        import io, sys
        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        try:
            from schema_setup import get_gspread_client, get_sheet_id
            gc = get_gspread_client()
            sh = gc.open_by_key(get_sheet_id())
            ws = sh.worksheet("Emails")
            rows = ws.get_all_records()   # reads from row 2 downwards (after headers)

            # Identify rows to delete: status is empty AND subject is empty
            VALID_STATUSES = {"queued", "sending", "sent", "delivered", "failed", "bounced"}
            to_delete = []
            for i, row in enumerate(rows, start=2):   # row index 1-based, data starts at 2
                status = str(row.get("status", "")).strip().lower()
                subject = str(row.get("subject", "")).strip()
                if status not in VALID_STATUSES and not subject:
                    to_delete.append(i)

            sys.stdout = old_stdout
            if not to_delete:
                st.info("No orphaned rows found — the tab is clean.")
            else:
                # Delete in REVERSE order so row indices don't shift
                for row_num in reversed(to_delete):
                    ws.delete_rows(row_num)
                SheetCache.invalidate("Emails")
                st.success(f"✅ Deleted {len(to_delete)} orphaned row(s): {to_delete}")
        except Exception as e:
            sys.stdout = old_stdout
            st.error(f"❌ {type(e).__name__}: {e}")

    st.divider()
    if st.button("← Back to campaign setup"):
        _go("stage1")


# ============================================================================
# MAIN
# ============================================================================

def main():
    # First-run gate: if the Sheet isn't initialized, show a one-click setup
    # screen and halt. No-op once the schema is ready.
    ensure_schema_ready()

    # Identify the user once (used for audit trail across the app).
    # ensure_user_identified() halts with st.stop() until a user is chosen.
    ensure_user_identified()

    _render_sidebar()
    _route()


if __name__ == "__main__":
    main()
