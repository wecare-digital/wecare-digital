    logger.info(json.dumps({"event": "vault_native_payment_requested",
                            "fileId": str(item.get("fileId") or ""),
                            "outcome": outcome, "renewal": False,
                            # Carry the business-api answer's sub-reason/detail so a refusal is
                            # diagnosable from one log line. The outcome alone (PAYMENT_REQUEST_REFUSED)
                            # collapses several distinct causes (delivery-confirmation digest mismatch,
                            # intent unavailable, sender not permitted, commerce prepare refusal).
                            "reason": str((answer or {}).get("reason") or "")[:80],
                            "detail": str((answer or {}).get("detail")
                                          or (answer or {}).get("message") or "")[:120],
                            "requestedBy": str(requested_by or "")[:32]}))