"""Creator-only evaluation of proposed Web Chat prompt changes."""

import os
from threading import Lock

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app import auth, database
from app.web_chat import WEB_SYSTEM_PROMPT


router = APIRouter(prefix="/dashboard/improvement")
evaluation_lock = Lock()


class Evaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(min_length=1, max_length=1500)
    candidate_instruction: str = Field(min_length=1, max_length=1200)
    expected_text: str = Field(min_length=1, max_length=240)


def require_creator(request):
    user = auth.get_current_identity(request)
    if not user:
        raise HTTPException(401, "Please sign in.")
    if not user.get("profile_completed") or not user.get("is_creator"):
        raise HTTPException(403, "Creator access is required.")
    if request.method != "GET":
        auth.require_same_origin(request)


@router.get("")
def feedback_summary(request: Request, response: Response):
    require_creator(request)
    response.headers["Cache-Control"] = "no-store"
    with database.get_connection() as db:
        rows = db.execute("""
            SELECT f.improvement_category AS category, COUNT(*) AS count
            FROM web_response_feedback f
            JOIN memories m ON m.id = f.memory_id
            JOIN web_messages msg ON msg.id = f.message_id
            WHERE f.rating = 'bad' AND f.improvement_category IS NOT NULL
              AND m.archived_at IS NULL
            GROUP BY f.improvement_category
            ORDER BY count DESC, category
        """).fetchall()
    return {"categories": [dict(row) for row in rows]}


def completion(client, base_url, model, question, system_prompt):
    result = client.post(
        f"{base_url}/chat/completions",
        json={
            "model": model, "stream": False, "temperature": 0, "max_tokens": 800,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        },
    )
    result.raise_for_status()
    choice = result.json()["choices"][0]
    answer = choice["message"]["content"]
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Empty evaluation response")
    truncated = choice.get("finish_reason") in ("length", "max_tokens") or len(answer) > 5000
    return answer[:5000].strip(), truncated


@router.post("")
def evaluate(payload: Evaluation, request: Request, response: Response):
    require_creator(request)
    response.headers["Cache-Control"] = "no-store"
    key = os.getenv("NINE_ROUTER_API_KEY", "").strip()
    if not key:
        raise HTTPException(503, "9Router is not configured.")
    base_url = os.getenv("NINE_ROUTER_BASE_URL", "http://9router:20128/v1").rstrip("/")
    model = os.getenv("NINE_ROUTER_MODEL", "Abud-Combo")
    if not evaluation_lock.acquire(blocking=False):
        raise HTTPException(409, "An evaluation is already running.")
    try:
        with httpx.Client(headers={"Authorization": f"Bearer {key}"}, timeout=20) as client:
            baseline, baseline_truncated = completion(client, base_url, model, payload.question, WEB_SYSTEM_PROMPT)
            candidate, candidate_truncated = completion(
                client, base_url, model, payload.question,
                WEB_SYSTEM_PROMPT + "\n\nEvaluation-only instruction:\n" + payload.candidate_instruction,
            )
    except httpx.TimeoutException:
        raise HTTPException(504, "Evaluation timed out.") from None
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
        raise HTTPException(502, "Evaluation could not obtain two valid answers.") from None
    finally:
        evaluation_lock.release()

    expected = " ".join(payload.expected_text.casefold().split())
    baseline_match = expected in " ".join(baseline.casefold().split())
    candidate_match = expected in " ".join(candidate.casefold().split())
    return {
        "model": model,
        "baseline": {"answer": baseline, "matched": baseline_match, "truncated": baseline_truncated},
        "candidate": {"answer": candidate, "matched": candidate_match, "truncated": candidate_truncated},
        "recommendation": (
            "review_candidate" if candidate_match and not baseline_match
            and not baseline_truncated and not candidate_truncated else "needs_more_evidence"
        ),
    }
