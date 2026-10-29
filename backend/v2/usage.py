"""Normalize provider observations without guessing allowance from token counts."""

import math


def allowance(snapshot):
    buckets = snapshot.get("rateLimitsByLimitId") or {}
    if not buckets and snapshot.get("rateLimits"):
        buckets = {"codex": snapshot["rateLimits"]}
    windows = []
    for bucket_id, bucket in buckets.items():
        if not isinstance(bucket, dict):
            continue
        for period in ("primary", "secondary"):
            window = bucket.get(period) or {}
            used = window.get("usedPercent")
            if type(used) not in (int, float) or not math.isfinite(used):
                continue
            duration = window.get("windowDurationMins")
            duration = duration if type(duration) is int and duration > 0 else None
            reset = window.get("resetsAt")
            reset = (
                int(reset)
                if type(reset) in (int, float) and math.isfinite(reset) and reset > 0
                else None
            )
            label = (
                "5-hour"
                if duration == 300
                else "Weekly"
                if duration == 10080
                else f"{duration // 60}-hour"
                if duration and duration % 60 == 0
                else f"{duration}-minute"
                if duration
                else "Usage window"
            )
            windows.append(
                {
                    "bucket": bucket_id,
                    "bucket_label": bucket.get("limitName") or bucket_id,
                    "period": period,
                    "label": label,
                    "remaining_percent": max(0, min(100, 100 - used)),
                    "duration_minutes": duration,
                    "resets_at": reset,
                }
            )
    windows.sort(key=lambda w: (w["bucket"] != "codex", w["period"] != "primary"))
    return {
        "available": bool(windows),
        "windows": windows,
        "message": "Reported by Codex"
        if windows
        else "Allowance not reported by this connection.",
    }


def tokens(observation):
    usage = observation.get("tokenUsage") or {}
    total = usage.get("total") or {}
    result = {}
    for name in (
        "totalTokens",
        "inputTokens",
        "cachedInputTokens",
        "outputTokens",
        "reasoningOutputTokens",
    ):
        value = total.get(name)
        if type(value) is int and value >= 0:
            result[name] = value
    limit = usage.get("modelContextWindow")
    if type(limit) is int and limit > 0:
        result["modelContextWindow"] = limit
    return result


def merge_allowance(previous, snapshot):
    update = allowance(snapshot)
    incoming = {(w["bucket"], w["period"]) for w in update["windows"]}
    update["windows"] += [
        w
        for w in previous.get("windows", [])
        if (w["bucket"], w["period"]) not in incoming
    ]
    update["windows"].sort(
        key=lambda w: (w["bucket"] != "codex", w["period"] != "primary")
    )
    update["available"] = bool(update["windows"])
    return update
