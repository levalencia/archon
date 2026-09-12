"""Application service joining trusted context resolution with grounded tutoring."""

from __future__ import annotations

from app.learning_tutor.context import LearningContextRequest, LearningContextResolver
from app.learning_tutor.repository import LearningTutorRepository, TutorSession
from app.learning_tutor.workflow import LearningTutorResult, LearningTutorWorkflow


class LearningTutorService:
    def __init__(
        self,
        *,
        resolver: LearningContextResolver,
        workflow: LearningTutorWorkflow,
        sessions: LearningTutorRepository,
    ) -> None:
        self._resolver = resolver
        self._workflow = workflow
        self._sessions = sessions

    async def ask(
        self,
        *,
        question: str,
        context_request: LearningContextRequest,
        owner_id: str,
        project_id: str,
        correlation_id: str,
    ) -> LearningTutorResult:
        context = self._resolver.resolve(context_request)
        return await self._workflow.answer(
            question=question,
            context=context,
            owner_id=owner_id,
            project_id=project_id,
            correlation_id=correlation_id,
        )

    async def history(self, *, session_id: str, owner_id: str) -> TutorSession | None:
        return await self._sessions.get_session(session_id, owner_id=owner_id)
