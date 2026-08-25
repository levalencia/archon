"""Multi-agent coordinator route — non-streaming JSON endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.agents.llm_factory import create_llm_client
from app.agents.multi_agent import (
    PlannerAgent,
    RetrieverAgent,
    SynthesizerAgent,
    ValidatorAgent,
)
from app.agents.resilient_coordinator import ResilientCoordinator
from app.security.auth import get_current_user

router = APIRouter(prefix="/api/chat", tags=["chat"])


class MultiAgentRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    conversation_id: str = ""


@router.post("/multi-agent")
async def multi_agent_chat(
    body: MultiAgentRequest,
    request: Request,
    user: dict = Depends(get_current_user),  # noqa: B008
) -> dict:
    """Run a query through the multi-agent coordinator pipeline."""
    settings = request.app.state.settings

    llm = create_llm_client(settings)

    coordinator = ResilientCoordinator(
        planner=PlannerAgent(llm),
        retriever=RetrieverAgent(llm),
        validator=ValidatorAgent(llm),
        synthesizer=SynthesizerAgent(llm),
    )

    result = await coordinator.orchestrate(body.message)

    return {
        "answer": result["answer"],
        "agents_used": result["agents_used"],
        "iterations": len(result["steps"]),
        "token_budget_report": {
            "pipeline": result["pipeline"],
            "steps_completed": len(result["steps"]),
        },
    }
