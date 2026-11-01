"""Fail-closed, Admin-only Meta draft asset policy for F008 Referral.

This module authorizes *one existing draft* for asset read/write without adding
it to the published canonical customer Flow registry or exposing other drafts.
It does not publish, send messages, or alter WABA/app settings.
"""
from __future__ import annotations

from typing import Any

F008_FLOW_ID = "1933489271340286"
F008_META_NAME = "WD-F008- Referal"


def is_f008_draft(flow_id: Any, provider_flow: Any, waba_id: str, app_id: str) -> bool:
    """Trust a fresh Meta GET, not the caller's claimed Flow status or ownership."""
    if str(flow_id or "") != F008_FLOW_ID or not isinstance(provider_flow, dict):
        return False
    owner = provider_flow.get("whatsapp_business_account")
    application = provider_flow.get("application")
    if not isinstance(owner, dict) or not isinstance(application, dict):
        return False
    return (
        str(provider_flow.get("id") or "") == F008_FLOW_ID
        and provider_flow.get("name") == F008_META_NAME
        and provider_flow.get("status") == "DRAFT"
        and str(owner.get("id") or "") == str(waba_id)
        and str(application.get("id") or "") == str(app_id)
    )
