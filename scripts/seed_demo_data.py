"""Seed realistic synthetic applicant data for SJBIT 2026-27 Recruitment."""

from __future__ import annotations

import os
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("USE_LOCAL_STORE", "true")
os.environ.setdefault("ENVIRONMENT", "dev")
os.environ.setdefault("AI_PROVIDER", "mock")

from backend.src.common.models import Applicant, utcnow
from backend.src.common.repository import get_repository
from backend.src.pipeline.tasks import process_applicant_now

CANDIDATES = [
    {
        "name": "Aditya Rao",
        "email": "aditya.rao.22@sjbit.edu.in",
        "usn": "1JB22CS014",
        "dept": "Computer Science and Engineering",
        "year": "3rd Year",
        "role": "Technical Team",
        "skills": "AWS Lambda, Python, Docker, React, DynamoDB",
        "projects": "Built an automated campus event management portal deployed on AWS S3 and CloudFront.",
    },
    {
        "name": "Ananya Hegde",
        "email": "ananya.hegde.23@sjbit.edu.in",
        "usn": "1JB23IS028",
        "dept": "Information Science and Engineering",
        "year": "2nd Year",
        "role": "Creative & Design",
        "skills": "Figma, UI/UX Design, Adobe Illustrator, Canva, CSS",
        "projects": "Designed official UI mockups and design systems for departmental hackathons.",
    },
    {
        "name": "Karthik Venkatesh",
        "email": "karthik.v.22@sjbit.edu.in",
        "usn": "1JB22EC052",
        "dept": "Electronics and Communication",
        "year": "3rd Year",
        "role": "Marketing & Outreach",
        "skills": "Public speaking, Corporate sponsorship outreach, Community organizing",
        "projects": "Organized inter-college tech symposium with 800+ attendees and 4 corporate sponsors.",
    },
    {
        "name": "Sneha Kulkarni",
        "email": "sneha.k.23@sjbit.edu.in",
        "usn": "1JB23AI089",
        "dept": "Artificial Intelligence and Data Science",
        "year": "2nd Year",
        "role": "Technical Team",
        "skills": "PyTorch, FastAPI, DeepSeek API, NLP, LangChain",
        "projects": "Developed a student chatbot using LLM embeddings and vector search.",
    },
    {
        "name": "Rohan Deshmukh",
        "email": "rohan.d.22@sjbit.edu.in",
        "usn": "1JB22ME033",
        "dept": "Mechanical Engineering",
        "year": "3rd Year",
        "role": "Operations & Logistics",
        "skills": "Event coordination, Venue management, Resource budgeting",
        "projects": "Head of logistics for annual college festival managing sound, lighting, and vendor contracts.",
    },
    {
        "name": "Meera Nambiar",
        "email": "meera.n.24@sjbit.edu.in",
        "usn": "1JB24CS112",
        "dept": "Computer Science and Engineering",
        "year": "1st Year",
        "role": "Social Media",
        "skills": "Content creation, Reels editing, LinkedIn personal branding, Copywriting",
        "projects": "Managed tech club Instagram page, growing engagement by 320% in 4 months.",
    },
    {
        "name": "Varun Gowda",
        "email": "varun.g.22@sjbit.edu.in",
        "usn": "1JB22CS180",
        "dept": "Computer Science and Engineering",
        "year": "3rd Year",
        "role": "Technical Team",
        "skills": "Terraform, AWS CDK, Kubernetes, Node.js, PostgreSQL",
        "projects": "Implemented multi-environment CI/CD pipeline on AWS for student developer club.",
    },
]


def seed():
    repo = get_repository()
    print("Seeding synthetic candidates for AWS Student Builder Group (SJBIT)...")

    for i, c in enumerate(CANDIDATES):
        app_id = f"APP-2026-{i+1:03d}"
        applicant = Applicant(
            applicant_id=app_id,
            source_response_id=f"GFORM-2026-{i+1:04d}",
            submitted_at=utcnow(),
            full_name=c["name"],
            email=c["email"],
            usn=c["usn"],
            department=c["dept"],
            year_of_study=c["year"],
            roles=[c["role"]],
            phone="+91 98765 43210",
            responses={
                "Full Name": c["name"],
                "Email Address": c["email"],
                "University Seat Number (USN)": c["usn"],
                "Department": c["dept"],
                "Year of Study": c["year"],
                "Which team(s) are you applying for?": c["role"],
                "technical_skills": c["skills"],
                "projects": c["projects"],
                "experience": "Active student developer at SJBIT.",
                "motivation": "Passionate about AWS cloud technologies and peer mentorship.",
                "availability": "10 hours per week",
            },
            processing_status="QUEUED",
        )
        repo.save_applicant(applicant)
        print(f"Created applicant {app_id}: {c['name']} ({c['role']})")

        # Process through extraction, AI evaluation, and scoring
        try:
            result = process_applicant_now(app_id)
            print(f"  -> Evaluated & Scored: {result.get('total_score')} points ({result.get('recommendation')})")
        except Exception as exc:
            print(f"  -> Evaluation note: {exc}")

    print("\nSeeding complete! Start the dev server or dashboard to explore candidate profiles.")


if __name__ == "__main__":
    seed()

