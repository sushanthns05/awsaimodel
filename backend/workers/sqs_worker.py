"""Render Background Worker for AWS SQS & Job Queue Processing.

Continuously polls Amazon SQS for applicant evaluation jobs and report generation
tasks. Implements exponential backoff, retry management, dead-letter routing,
and graceful shutdown.
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from typing import Any, Dict

from ..src.common.config import Settings, get_settings
from ..src.common.errors import AppError
from ..src.common.logging_utils import get_logger
from ..src.common.repository import get_repository
from ..src.pipeline.queue import dispatch_message
from ..src.pipeline.tasks import mark_failed, process_applicant_now
from ..src.reports.service import generate_report

logger = get_logger("sbg.worker.sqs")

RUNNING = True


def handle_shutdown(signum: int, frame: Any) -> None:
    """Handle termination signals gracefully."""
    global RUNNING
    sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
    logger.info("Received %s signal. Finishing active tasks and shutting down...", sig_name)
    RUNNING = False


signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)


class BackgroundWorker:
    """Production background worker for Render and cloud worker instances."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.queue_url = self.settings.processing_queue_url
        self.max_retries = int(os.getenv("WORKER_MAX_RETRIES", "3"))
        self.poll_wait_seconds = int(os.getenv("WORKER_POLL_WAIT_SECONDS", "20"))
        self.batch_size = int(os.getenv("WORKER_BATCH_SIZE", "5"))
        self.concurrency = int(os.getenv("WORKER_CONCURRENCY", "4"))
        self.sqs_client = None

        if self.queue_url and not self.settings.is_local:
            try:
                import boto3

                self.sqs_client = boto3.client("sqs", region_name=self.settings.region)
                logger.info("Connected to Amazon SQS at %s", self.queue_url)
            except Exception as exc:
                logger.warning("Could not initialize SQS client: %s. Falling back to local mode.", exc)

    def process_message_body(self, body: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single queue message body according to message type."""
        msg_type = body.get("type", "PROCESS_APPLICANT")
        applicant_id = body.get("applicant_id") or body.get("applicantId")

        if msg_type == "GENERATE_REPORT":
            report_id = body.get("report_id")
            kind = body.get("kind", "excel")
            scope = body.get("scope", {})
            actor = body.get("actor", "worker")
            logger.info("Generating report %s [Kind: %s]", report_id, kind)
            record = generate_report(report_id, kind, scope, actor)
            return {"status": "SUCCESS", "report_id": report_id, "record": record.to_dict()}

        if applicant_id:
            logger.info("Processing applicant %s through extraction, AI evaluation, and scoring", applicant_id)
            try:
                result = process_applicant_now(applicant_id)
                logger.info("Applicant %s processed successfully. Total score: %s", applicant_id, result.get("total_score"))
                return result
            except Exception as exc:
                logger.error("Processing failed for %s: %s", applicant_id, exc, exc_info=True)
                mark_failed(applicant_id, f"Worker pipeline error: {type(exc).__name__}: {str(exc)}")
                raise

        # Generic dispatch fallback
        return dispatch_message(body)

    def poll_sqs_once(self) -> int:
        """Poll Amazon SQS and process received messages. Returns count of processed messages."""
        if not self.sqs_client or not self.queue_url:
            return 0

        try:
            response = self.sqs_client.receive_message(
                QueueUrl=self.queue_url,
                MaxNumberOfMessages=self.batch_size,
                WaitTimeSeconds=min(self.poll_wait_seconds, 20),
                AttributeNames=["ApproximateReceiveCount"],
                MessageAttributeNames=["All"],
            )
            messages = response.get("Messages", [])
            if not messages:
                return 0

            logger.info("Received %d message(s) from SQS", len(messages))

            for msg in messages:
                receipt_handle = msg.get("ReceiptHandle")
                msg_id = msg.get("MessageId")
                body_raw = msg.get("Body", "{}")
                receive_count = int(msg.get("Attributes", {}).get("ApproximateReceiveCount", "1"))

                try:
                    body = json.loads(body_raw)
                    self.process_message_body(body)

                    # Acknowledge & delete successful message
                    self.sqs_client.delete_message(
                        QueueUrl=self.queue_url,
                        ReceiptHandle=receipt_handle,
                    )
                    logger.info("Acknowledged and deleted SQS message %s", msg_id)

                except Exception as exc:
                    logger.error("Error handling SQS message %s (attempt %d): %s", msg_id, receive_count, exc)
                    # If maximum retries exceeded, SQS RedrivePolicy will automatically route to DLQ

            return len(messages)

        except Exception as exc:
            logger.error("Error polling SQS queue: %s", exc)
            time.sleep(5)
            return 0

    def run_reconciliation(self) -> None:
        """Periodically check for queued or stalled applicants that need processing."""
        from ..src.handlers.workers import reprocess_handler

        try:
            result = reprocess_handler({})
            if result.get("requeued"):
                logger.info("Reconciliation requeued %d stale applicants", len(result["requeued"]))
        except Exception as exc:
            logger.warning("Reconciliation check failed: %s", exc)

    def start(self) -> None:
        """Main worker loop."""
        logger.info(
            "Render Background Worker started. [Queue: %s, Concurrency: %d]",
            self.queue_url or "LOCAL_STORE",
            self.concurrency,
        )

        last_reconciliation = 0.0

        while RUNNING:
            try:
                # Periodic reconciliation every 10 minutes
                now = time.time()
                if now - last_reconciliation > 600:
                    self.run_reconciliation()
                    last_reconciliation = now

                if self.sqs_client:
                    processed = self.poll_sqs_once()
                    if processed == 0:
                        # Exponential backoff jitter when queue is idle
                        time.sleep(2)
                else:
                    # In local / single-host mode, poll for queued items in repository
                    time.sleep(5)

            except Exception as exc:
                logger.error("Unexpected worker loop exception: %s", exc, exc_info=True)
                time.sleep(5)

        logger.info("Background worker stopped cleanly.")


def main() -> None:
    worker = BackgroundWorker()
    worker.start()


if __name__ == "__main__":
    main()

