"""Queue / Step Functions dispatch and a synchronous local runner."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from ..common.config import Settings, get_settings
from ..common.errors import AppError
from ..common.logging_utils import get_logger
from ..common.models import iso, utcnow
from ..common.repository import Repository, get_repository

logger = get_logger("sbg.queue")


def enqueue_processing(
    applicant_id: str,
    *,
    force: bool = False,
    repo: Optional[Repository] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = repo or get_repository()
    message = {
        "applicant_id": applicant_id,
        "force": bool(force),
        "requested_at": iso(utcnow()),
        "schema_version": 1,
    }

    if settings.processing_queue_url:
        try:
            import boto3

            sqs = boto3.client("sqs", region_name=settings.region)
            response = sqs.send_message(
                QueueUrl=settings.processing_queue_url,
                MessageBody=json.dumps(message),
                MessageAttributes={
                    "applicant_id": {"DataType": "String", "StringValue": applicant_id},
                },
            )
            return {"mode": "sqs", "message_id": response.get("MessageId"), "applicant_id": applicant_id}
        except Exception as exc:  # noqa: BLE001
            logger.error("SQS enqueue failed for %s: %s", applicant_id, type(exc).__name__)
            raise AppError("Unable to queue applicant for processing") from exc

    if settings.state_machine_arn:
        try:
            import boto3

            sfn = boto3.client("stepfunctions", region_name=settings.region)
            name = f"{applicant_id}-{int(time.time())}"
            response = sfn.start_execution(
                stateMachineArn=settings.state_machine_arn,
                name=name[:80],
                input=json.dumps(message),
            )
            return {"mode": "stepfunctions", "execution_arn": response.get("executionArn")}
        except Exception as exc:  # noqa: BLE001
            logger.error("Step Functions start failed for %s: %s", applicant_id, type(exc).__name__)
            raise AppError("Unable to start processing workflow") from exc

    if settings.is_local:
        return {"mode": "local", "applicant_id": applicant_id}

    raise AppError("Processing queue is not configured")


def dispatch_message(message: dict[str, Any], *, settings: Optional[Settings] = None) -> dict[str, Any]:
    """SQS consumer entry: start a Step Functions execution per applicant."""
    settings = settings or get_settings()
    applicant_id = str(message.get("applicant_id") or "")
    if not applicant_id:
        raise AppError("Queue message is missing applicant_id")
    repo = get_repository()

    # Idempotency: skip duplicates that have already completed unless forced.
    try:
        applicant = repo.get_applicant(applicant_id)
        if (
            not message.get("force")
            and applicant.processing_status in ("COMPLETED", "NEEDS_REVIEW")
            and applicant.latest_evaluation_id
        ):
            return {"status": "SKIPPED", "applicant_id": applicant_id}
        applicant.processing_status = "QUEUED"
        repo.save_applicant(applicant)
    except Exception:  # noqa: BLE001
        logger.warning("Applicant %s not found while dispatching", applicant_id)
        return {"status": "NOT_FOUND", "applicant_id": applicant_id}

    if settings.state_machine_arn:
        import boto3

        sfn = boto3.client("stepfunctions", region_name=settings.region)
        response = sfn.start_execution(
            stateMachineArn=settings.state_machine_arn,
            name=f"{applicant_id}-{int(time.time())}-{message.get('requested_at', '')}"[:80].replace(":", "-").replace(".", "-").replace("+", "-"),
            input=json.dumps(message),
        )
        return {"status": "STARTED", "execution_arn": response.get("executionArn")}
    return {"status": "QUEUED", "applicant_id": applicant_id}
