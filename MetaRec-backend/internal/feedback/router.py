"""User feedback API — thumb up / thumb down on recommendation results.

Mounted at ``/api/feedback`` and gated on an authenticated **registered** session
(guests are blocked at the API even though the UI hides the control — defense in
depth). The vote maps to the existing ``feedback`` table: sentiment -> ``rating``
(the dashboard's satisfaction signal) and the dislike reason -> ``label`` (the
"why unsatisfied" histogram). Reasons are gated against a fixed backend enum.
"""
from __future__ import annotations

from typing import Any, Callable, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from business_models import (
    FEEDBACK_REASON_LABELS,
    AuthSessionPayload,
    FeedbackReason,
    FeedbackSentiment,
    feedback_reasons_for_domain,
)
from business_repositories import feedback_repository


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FeedbackCreateAPI(StrictBaseModel):
    # Sentiment is required; reason only applies to a thumb-down (single-select).
    sentiment: FeedbackSentiment
    reason: Optional[FeedbackReason] = None
    # The result the vote attaches to. Prefer an explicit result_id; otherwise the
    # server derives the stable id from (task_id, branch_id).
    result_id: Optional[str] = None
    task_id: Optional[str] = None
    branch_id: Optional[str] = None
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None


class FeedbackOptionAPI(StrictBaseModel):
    code: str
    label: str


class FeedbackOptionsAPI(StrictBaseModel):
    reasons: List[FeedbackOptionAPI]


def create_feedback_router(require_session: Callable[..., Any]) -> APIRouter:
    router = APIRouter(prefix="/api/feedback", tags=["feedback"])

    @router.get("/options", response_model=FeedbackOptionsAPI)
    async def feedback_options(
        domain: Optional[str] = None,
        _: AuthSessionPayload = Depends(require_session),
    ):
        # Single source of truth for the FE dislike-reason chips. The offered set is
        # domain-aware (e.g. "Too far" only for restaurant); the POST endpoint still
        # validates against the full union so any code remains acceptable.
        return FeedbackOptionsAPI(
            reasons=[
                FeedbackOptionAPI(code=code, label=FEEDBACK_REASON_LABELS[code])
                for code in feedback_reasons_for_domain(domain)
            ]
        )

    @router.post("")
    async def submit_feedback(
        payload: FeedbackCreateAPI,
        session: AuthSessionPayload = Depends(require_session),
    ):
        # Guests cannot leave feedback (the UI also hides the control for them).
        if session.user.kind != "registered":
            raise HTTPException(status_code=403, detail="Only registered users can leave feedback")

        try:
            feedback = await feedback_repository.submit(
                user_id=session.user.id,
                sentiment=payload.sentiment,
                reason=payload.reason,
                result_id=payload.result_id,
                task_id=payload.task_id,
                branch_id=payload.branch_id,
                conversation_id=payload.conversation_id,
                ui_message_id=payload.message_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "feedback": feedback}

    return router
