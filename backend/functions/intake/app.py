import os
import json
import uuid
import hmac
import boto3
from datetime import datetime, timezone

dynamodb = boto3.resource("dynamodb")
sqs = boto3.client("sqs")

TABLE_NAME = os.environ["APPLICANTS_TABLE"]
QUEUE_URL = os.environ["PROCESSING_QUEUE_URL"]
INGEST_SECRET = os.environ["INGEST_SECRET"]

table = dynamodb.Table(TABLE_NAME)


def response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps(body)
    }


def handler(event, context):

    headers = event.get("headers") or {}

    supplied_secret = (
        headers.get("X-Ingest-Secret")
        or headers.get("x-ingest-secret")
        or ""
    )

    if not hmac.compare_digest(
        supplied_secret,
        INGEST_SECRET
    ):
        return response(401, {
            "error": "Unauthorized"
        })

    try:
        applicant = json.loads(event.get("body") or "{}")

        required = ["name", "email", "applied_role"]

        if not all(applicant.get(key) for key in required):
            return response(400, {
                "error": "Missing required applicant fields"
            })

        applicant_id = "AWS-" + uuid.uuid4().hex[:12].upper()

        record = {
            **applicant,
            "applicant_id": applicant_id,
            "email": applicant["email"].strip().lower(),
            "status": "RECEIVED",
            "created_at": datetime.now(
                timezone.utc
            ).isoformat()
        }

        table.put_item(
            Item=record,
            ConditionExpression="attribute_not_exists(applicant_id)"
        )

        sqs.send_message(
            QueueUrl=QUEUE_URL,
            MessageBody=json.dumps({
                "applicant_id": applicant_id
            })
        )

        return response(202, {
            "success": True,
            "applicant_id": applicant_id,
            "status": "RECEIVED"
        })

    except Exception:
        # Do not log application content or secrets.
        print("Applicant intake failed")
        return response(500, {
            "error": "Unable to process application"
        })