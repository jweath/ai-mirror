from __future__ import annotations

import hashlib
import hmac
import time

import httpx


def verify_signature(secret: str, raw: bytes, timestamp: str, signature: str, now=None):
    if not secret:
        return False
    try:
        if abs((time.time() if now is None else now) - int(timestamp)) > 300:
            return False
    except (TypeError, ValueError):
        return False
    expected = "v0=" + hmac.new(secret.encode(), b"v0:" + timestamp.encode() + b":" + raw,
                                 hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


class SlackError(Exception):
    def __init__(self, code, uncertain=False):
        self.code = code
        self.uncertain = uncertain
        super().__init__(code)


class Slack:
    def __init__(self, token):
        self.token = token

    def call(self, method, payload):
        if not self.token:
            raise SlackError("missing_slack_token")
        try:
            response = httpx.post(f"https://slack.com/api/{method}", json=payload,
                                  headers={"Authorization": f"Bearer {self.token}"}, timeout=15)
        except httpx.HTTPError:
            raise SlackError("network_outcome_unknown", uncertain=True) from None
        if response.status_code == 429:
            raise SlackError("rate_limited")
        if response.status_code >= 500:
            raise SlackError("provider_outcome_unknown", uncertain=True)
        try:
            data = response.json()
        except ValueError:
            raise SlackError("invalid_provider_response", uncertain=True) from None
        if response.status_code != 200 or not data.get("ok"):
            raise SlackError(str(data.get("error", "slack_rejected")))
        return data

    def post(self, payload):
        fields = {k: payload[k] for k in ("channel", "text", "thread_ts") if payload.get(k)}
        result = self.call("chat.postMessage", {**fields, "unfurl_links": False, "unfurl_media": False,
                                               "parse": "none"})
        if not result.get("ts"):
            raise SlackError("missing_delivery_receipt", uncertain=True)
        return result


def slack_link(workspace_id, channel, ts):
    # A workspace-independent permalink; no need for a workspace-name lookup.
    return f"https://app.slack.com/archives/{channel}/p{ts.replace('.', '')}?team={workspace_id}"


def plain_slack(text):
    """Prevent student/model text from becoming mass mentions or link markup."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
