from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, ValidationError

from apps.api.src.security import require_admin_access
from apps.common.src.email.client import EmailClient

router = APIRouter(tags=["ops"], prefix="/api/v1/ops", dependencies=[Depends(require_admin_access)])
logger = logging.getLogger(__name__)


class EmailRequest(BaseModel):
    to: Optional[List[EmailStr]] = None
    subject: str
    text: Optional[str] = None
    html: Optional[str] = None
    sender: Optional[EmailStr] = None


class EmailResponse(BaseModel):
    ok: bool


@router.post(
    "/email",
    response_model=EmailResponse,
    status_code=status.HTTP_200_OK,
    summary="Send an email via the configured SMTP provider.",
)
def send_email(request: EmailRequest):
    try:
        EmailClient.send(
            to=request.to,
            subject=request.subject,
            text=request.text,
            html=request.html,
            sender=request.sender,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Email send failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="email_send_failed",
        ) from exc
    return EmailResponse(ok=True)
