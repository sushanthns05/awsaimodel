"""Send a signed test submission to the FastAPI intake endpoint."""

import argparse
import hashlib
import hmac
import json
import os
import time
import urllib.request

parser = argparse.ArgumentParser(description="Test Google Form intake webhook")
parser.add_argument("--url", default="http://127.0.0.1:8000/api/intake", help="Intake endpoint URL")
parser.add_argument("--key", default="test-secret-key-1234", help="Shared intake secret key")
args = parser.parse_args()

ts = str(int(time.time()))
resp_id = f"TEST-FORM-{int(time.time()*1000)}"

payload = {
    "source_response_id": resp_id,
    "submitted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "answers": {
        "Full Name": "Siddharth Verma",
        "Email Address": "siddharth.v@sjbit.edu.in",
        "University Seat Number (USN)": "1JB23CS145",
        "Department": "Computer Science and Engineering",
        "Year of Study": "2nd Year",
        "Which team(s) are you applying for?": "Technical Team",
        "Why do you want to join AWS Student Builder Group?": "I love building cloud native apps with AWS CDK and serverless.",
        "technical_skills": "Python, TypeScript, AWS S3, DynamoDB, API Gateway",
        "projects": "Created a real-time collaborative code editor hosted on AWS ECS.",
    },
    "documents": [],
}

body = json.dumps(payload)
signature = hmac.new(
    args.key.encode("utf-8"),
    f"{ts}.{body}".encode("utf-8"),
    hashlib.sha256,
).hexdigest()

headers = {
    "Content-Type": "application/json",
    "x-intake-key": args.key,
    "x-timestamp": ts,
    "x-signature": signature,
}

req = urllib.request.Request(args.url, data=body.encode("utf-8"), headers=headers, method="POST")

try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"Status: {resp.status}")
        data = json.loads(resp.read().decode("utf-8"))
        print("Response:", json.dumps(data, indent=2))
except urllib.error.HTTPError as exc:
    print(f"HTTP Error {exc.code}: {exc.read().decode('utf-8')}")
except Exception as exc:
    print(f"Failed to connect: {exc}")

