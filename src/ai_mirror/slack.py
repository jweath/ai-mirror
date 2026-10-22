from __future__ import annotations

import hashlib
import hmac
import re
import threading
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
        self._last_post = {}
        self._post_lock = threading.Lock()

    def call(self, method, payload):
        if not self.token:
            raise SlackError("missing_slack_token")
        try:
            headers = {"Authorization": f"Bearer {self.token}"}
            if method in ("conversations.info", "conversations.members"):
                # These metadata methods reject JSON POST parameters in Slack's
                # live API even though history and chat methods accept them.
                response = httpx.get(f"https://slack.com/api/{method}", params=payload,
                                     headers=headers, timeout=15)
            else:
                response = httpx.post(f"https://slack.com/api/{method}", json=payload,
                                      headers=headers, timeout=15)
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
        # Slack normally permits roughly one message/second per channel. Partner
        # feedback can target the same channel twice in a batch.
        with self._post_lock:
            wait = 1.1 - (time.monotonic() - self._last_post.get(payload["channel"], 0))
            if wait > 0:
                time.sleep(wait)
            self._last_post[payload["channel"]] = time.monotonic()
            result = self.call("chat.postMessage", {**fields, "unfurl_links": False, "unfurl_media": False,
                                                   "parse": "none"})
        if not result.get("ts"):
            raise SlackError("missing_delivery_receipt", uncertain=True)
        return result


def slack_link(workspace_id, channel, ts, workspace_url=None):
    if workspace_url and re.fullmatch(r"https://[a-zA-Z0-9-]+\.slack\.com/?", workspace_url):
        return f"{workspace_url.rstrip('/')}/archives/{channel}/p{ts.replace('.', '')}"
    # If auth.test did not supply the workspace URL, link the channel and retain
    # exact message/thread IDs in the source record rather than invent a permalink.
    return f"https://slack.com/app_redirect?team={workspace_id}&channel={channel}"


def plain_slack(text):
    """Prevent student/model text from becoming mass mentions or link markup."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
