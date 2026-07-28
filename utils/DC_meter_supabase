import os
import logging

logger = logging.getLogger(__name__)

try:
    from supabase import create_client
    SUPABASE_LIB_AVAILABLE = True
except ImportError:
    SUPABASE_LIB_AVAILABLE = False

SUPABASE_URL = "https://zrzrngwxwuqsupudcayd.supabase.co"
SUPABASE_KEY = "sb_publishable_oWywyOZyl846i-HYT6PGGw_DqVOW7Bg"

_client = None
_warned = False


def _get_client():
    global _client, _warned
    if not SUPABASE_LIB_AVAILABLE:
        return None
    if _client is not None:
        return _client
    if not SUPABASE_URL or not SUPABASE_KEY:
        if not _warned:
            logger.warning("[supabase_push] SUPABASE_URL/SUPABASE_KEY not set — live push disabled.")
            _warned = True
        return None
    try:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.info("[supabase_push] Connected to Supabase.")
        return _client
    except Exception as e:
        if not _warned:
            logger.warning(f"[supabase_push] Couldn't connect to Supabase ({e}). Live push disabled.")
            _warned = True
        return None


def push_dcm_reading(device_id, forward_energy_kwh, active_power_kw, current_a, voltage_v, error):
    """Best-effort push of one DCM3366 reading to Supabase. Any
    failure just logs a warning — local CSV logging is unaffected."""
    client = _get_client()
    if client is None:
        return
    try:
        client.table("panel_readings").insert({
            "device_id": device_id,
            "forward_energy_kwh": forward_energy_kwh,
            "active_power_kw": active_power_kw,
            "current_a": current_a,
            "voltage_v": voltage_v,
            "error": error,
        }).execute()
    except Exception as e:
        logger.warning(f"[supabase_push] Push failed: {e}")
