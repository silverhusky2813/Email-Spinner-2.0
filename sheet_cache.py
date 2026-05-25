"""
sheet_cache.py
===============
Centralized per-tab read cache for Google Sheets.

WHY THIS EXISTS
---------------
The original codebase used st.cache_data on individual loader functions and
st.cache_data.clear() after every write. The clear() is a nuclear wipe —
it evicts ALL cached tabs regardless of which tab was actually written.
This caused cascading quota errors (429) because every check in Stage 3
re-fetched from scratch after the cache was wiped by a prior write.

This module replaces that pattern with per-tab TTL caching backed by
st.session_state, so a write to Campaigns never evicts the Suppression
cache, and vice versa.

PUBLIC API
----------
    load_tab(tab_name)               → list[dict]   (read, caches automatically)
    SheetCache.invalidate(tab_name)  → None          (bust one tab on write)
    SheetCache.invalidate_all()      → None          (schema migrations only)

USAGE IN LOADER FUNCTIONS
--------------------------
    # Before:
    @st.cache_data(ttl=60)
    def _load_emails() -> list[dict]:
        ...
        return ws.get_all_records()

    # After:
    def _load_emails() -> list[dict]:
        return load_tab("Emails")

USAGE IN WRITE FUNCTIONS
-------------------------
    # Before:
    st.cache_data.clear()

    # After:
    SheetCache.invalidate("Campaigns")   # only bust the tab you wrote to

TAB TTL REFERENCE
------------------
    Campaigns       60s   — frequent reads during Stage 1–3
    Emails          60s   — dedup, health, analytics
    Suppression    300s   — rarely changes
    Publishers      30s   — Stage 2 enrichment
    Presets        300s   — rarely changes
    cpm_rates      300s   — rarely changes
    sender_accounts 30s   — Stage 5/6 rotation + health
    send_log        30s   — Stage 5 rate-limit counters
"""

import time
from typing import Optional

import gspread
import streamlit as st


# ============================================================================
# TTL REGISTRY
# ============================================================================

_TAB_TTL: dict[str, int] = {
    "Campaigns":       60,
    "Emails":          60,
    "Suppression":    300,
    "Publishers":      30,
    "Presets":        300,
    "cpm_rates":      300,
    "sender_accounts": 30,
    "send_log":        30,
    "reply_log":      120,
    "tracking_meta":  120,
}
_DEFAULT_TTL = 60


# ============================================================================
# CACHE CLASS
# ============================================================================

class SheetCache:
    """
    Per-tab cache backed by st.session_state.

    Using session_state instead of st.cache_data gives us:
    - Full control over per-tab invalidation
    - No cross-tab collateral damage on writes
    - Per-user isolation (session_state is already per-user)
    """

    @staticmethod
    def _key(tab: str) -> str:
        return f"__sc_{tab}"

    @staticmethod
    def get(tab: str) -> Optional[list[dict]]:
        """Return cached data if still within TTL, else None."""
        entry = st.session_state.get(SheetCache._key(tab))
        if entry is None:
            return None
        ttl = _TAB_TTL.get(tab, _DEFAULT_TTL)
        if time.time() - entry["ts"] > ttl:
            return None
        return entry["data"]

    @staticmethod
    def put(tab: str, data: list[dict]) -> None:
        """Store data in cache with current timestamp."""
        st.session_state[SheetCache._key(tab)] = {
            "data": data,
            "ts": time.time(),
        }

    @staticmethod
    def invalidate(tab: str) -> None:
        """
        Evict a single tab from cache.

        Call this after any write to that tab so the next read fetches fresh
        data. Does NOT touch any other tab's cache.
        """
        st.session_state.pop(SheetCache._key(tab), None)

    @staticmethod
    def invalidate_all() -> None:
        """
        Evict all tabs. Use ONLY for schema migrations (setup_gate, migrate_all).
        Never call from normal read/write paths.
        """
        for key in list(st.session_state.keys()):
            if key.startswith("__sc_"):
                del st.session_state[key]

    @staticmethod
    def age_seconds(tab: str) -> Optional[float]:
        """Return seconds since last cache fill, or None if not cached."""
        entry = st.session_state.get(SheetCache._key(tab))
        if entry is None:
            return None
        return time.time() - entry["ts"]


# ============================================================================
# UNIVERSAL LOADER
# ============================================================================

def load_tab(
    tab_name: str,
    gc: Optional[object] = None,
    sheet_id: Optional[str] = None,
) -> list[dict]:
    """
    Load all records from a Sheet tab, using the per-tab cache.

    This is the single call-site for ALL Sheet reads. Every loader function
    in the codebase delegates here instead of calling ws.get_all_records()
    directly.

    Args:
        tab_name:  The worksheet name, e.g. "Campaigns"
        gc:        Optional pre-built gspread client (avoids an extra import
                   cycle when called from stage1_dedup which owns get_gspread_client)
        sheet_id:  Optional sheet ID override (defaults to st.secrets["sheet_id"])

    Returns:
        list of row dicts (empty list if tab not found or sheet is empty)
    """
    cached = SheetCache.get(tab_name)
    if cached is not None:
        return cached

    # Lazy import to avoid circular deps — stage1_dedup owns the client factory
    if gc is None:
        from stage1_dedup import get_gspread_client
        gc = get_gspread_client()

    if sheet_id is None:
        sheet_id = st.secrets["sheet_id"]

    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        return []

    data = ws.get_all_records()
    SheetCache.put(tab_name, data)
    return data
