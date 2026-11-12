"""Resolve accessible plan actors' names without changing authorization or IDs."""
import os
import re
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

SUBJECT = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")


def real_name(value, actor_id):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (not value or len(value) > 255 or value == actor_id
            or SUBJECT.fullmatch(value) or "@" in value
            or any(ord(c) < 32 for c in value)):
        return None
    return value


class UpgradeActorNames:
    """Request-local, bounded, exact-sub lookups in the existing identity pool.

    Missing profile names are reported honestly; never infer a name from an ID
    or email, scan the directory, persist grants, or change the recorded actor.
    """
    def __init__(self, client=None, pool_id=None, clock=time.monotonic):
        self.client = client
        self.pool_id = pool_id if pool_id is not None else os.environ.get("IDENTITY_USER_POOL_ID")
        self.cache = {}
        self.clock = clock
        self.started = clock()
        self.failed = False

    def resolve(self, actor_id, preferred=None):
        if not actor_id:
            return None
        name = real_name(preferred, actor_id)
        if name:
            return name
        if actor_id in self.cache:
            return self.cache[actor_id]
        name = None
        if (self.pool_id and isinstance(actor_id, str) and SUBJECT.fullmatch(actor_id)
                and not self.failed and len(self.cache) < 8 and self.clock() - self.started < 4):
            try:
                if self.client is None:
                    self.client = boto3.client("cognito-idp", config=Config(
                        connect_timeout=1, read_timeout=2,
                        retries={"mode": "standard", "total_max_attempts": 1}))
                page = self.client.list_users(UserPoolId=self.pool_id, Filter=f'sub = "{actor_id}"', Limit=2)
                matches = []
                for user in page.get("Users", []):
                    attrs = {a.get("Name"): a.get("Value") for a in user.get("Attributes", [])}
                    if attrs.get("sub") == actor_id:
                        matches.append(attrs)
                if len(matches) == 1:
                    attrs = matches[0]
                    name = real_name(attrs.get("name"), actor_id) or real_name(
                        " ".join(v for v in [attrs.get("given_name"), attrs.get("family_name")] if isinstance(v, str)), actor_id)
            except (ClientError, BotoCoreError):
                self.failed = True
        self.cache[actor_id] = name or "Name unavailable"
        return self.cache[actor_id]
