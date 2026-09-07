"""Scheduled publisher: at-least-once delivery, SKIP LOCKED, bounded transactions."""

import json
import os
import logging
import time
from .diagnostics import emit, phase, invocation

emit("outbox_module_import", "started")
from .database import transaction
emit("outbox_module_import", "completed")


@invocation
def lambda_handler(event, context):
    with phase("eventbridge_client"):
        import boto3
        from botocore.config import Config
        client = boto3.client("events", config=Config(
            connect_timeout=3, read_timeout=3,
            retries={"mode": "standard", "total_max_attempts": 1}))
    published = 0
    failed = 0
    # Batch is <=10 (EventBridge PutEvents limit). Failed rows remain pending.
    with transaction("EVENTS_DB_SECRET_ARN") as db:
        rows = db.execute(
            "SELECT * FROM platform.event_outbox WHERE published_at IS NULL "
            "ORDER BY attempts,created_at LIMIT 10 FOR UPDATE SKIP LOCKED"
        ).fetchall()
        backlog = db.execute(
            "SELECT count(*) AS pending, COALESCE(EXTRACT(EPOCH FROM now()-min(created_at)),0) AS age "
            "FROM platform.event_outbox WHERE published_at IS NULL"
        ).fetchone()

        def metrics():
            logging.getLogger(__name__).warning(
                json.dumps(
                    {
                        "_aws": {
                            "Timestamp": int(time.time() * 1000),
                            "CloudWatchMetrics": [
                                {
                                    "Namespace": "Navigan/Events",
                                    "Dimensions": [["Module"]],
                                    "Metrics": [
                                        {"Name": "OutboxPending", "Unit": "Count"},
                                        {"Name": "OutboxOldestAge", "Unit": "Seconds"},
                                        {"Name": "OutboxPublishFailures", "Unit": "Count"},
                                    ],
                                }
                            ],
                        },
                        "Module": "CustomerManagement",
                        "OutboxPending": backlog["pending"],
                        "OutboxOldestAge": float(backlog["age"]),
                        "OutboxPublishFailures": failed,
                    }
                )
            )

        if not rows:
            metrics()
            return {"published": 0}
        entries = [
            {
                "Source": "navigan.environment-management" if r["event_type"].startswith("Environment") else "navigan.customer-management",
                "DetailType": r["event_type"],
                "Detail": json.dumps(r["payload"]),
                "EventBusName": os.environ["EVENT_BUS_NAME"],
            }
            for r in rows
        ]
        with phase("eventbridge_publish", batchSize=len(entries)):
            result = client.put_events(Entries=entries)
        emit("eventbridge_result", "completed", failedCount=result.get("FailedEntryCount", 0))
        for row, outcome in zip(rows, result["Entries"], strict=True):
            if "EventId" in outcome:
                db.execute(
                    "UPDATE platform.event_outbox SET published_at=now(), attempts=attempts+1,last_error=NULL WHERE event_id=%s",
                    [row["event_id"]],
                )
                published += 1
            else:
                failed += 1
                db.execute(
                    "UPDATE platform.event_outbox SET attempts=attempts+1,last_error=%s WHERE event_id=%s",
                    [outcome.get("ErrorCode", "PublishFailed")[:100], row["event_id"]],
                )
        metrics()
    emit("outbox_result", "completed", published=published, failed=failed)
    return {"published": published, "failed": failed}
