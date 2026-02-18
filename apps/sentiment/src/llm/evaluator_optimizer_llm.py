"""
Local subclass of EvaluatorOptimizerLLM that avoids duplicating the evaluator
criteria in the user message. The evaluator Agent's instruction is already
supplied to the model as a developer/system message by the LLM wrappers, so we
only include the request, the current response, and the required output format
in the user prompt.
"""

from __future__ import annotations

import re

from mcp_agent.workflows.evaluator_optimizer.evaluator_optimizer import (
    EvaluatorOptimizerLLM as _BaseEvaluatorOptimizerLLM,
)


class EvaluatorOptimizerLLMNoDup(_BaseEvaluatorOptimizerLLM):
    """Evaluator-optimizer that does not re-embed evaluator criteria in user prompts."""

    @staticmethod
    def _sanitize_request_text(text: str) -> str:
        """Remove orchestration-level agent references and keep only the concrete task.

        - Drops planner boilerplate like "You are part of a larger workflow" and plan context.
        - Removes references to agent/component names (research_quality_controller, search_finder, research_evaluator, EvaluatorOptimizerLLM).
        - If a line like "Your job is to accomplish only the following task:" exists, keep from there onward.
        """
        if not isinstance(text, str) or not text:
            return text

        # If the task delimiter exists, focus on that part onward
        anchor = re.search(
            r"Your job is to accomplish only the following task:\s*", text, re.IGNORECASE
        )
        if anchor:
            text = text[anchor.end() :].lstrip()
        else:
            # Otherwise, drop planner boilerplate header if present
            text = re.sub(
                r"^You are part of a larger workflow[\s\S]*?\n\n",
                "",
                text,
                flags=re.IGNORECASE,
            )

        # Remove explicit references to orchestration agents/components
        # Replace directive lines that instruct to use/run the controller with a neutral directive
        text = re.sub(
            r"(?i)\b(?:use|run)\s+research_quality_controller\b[^\n]*",
            "Gather comprehensive, up-to-date research as specified.",
            text,
        )
        text = re.sub(r"research_quality_controller", "", text, flags=re.IGNORECASE)
        text = re.sub(r"EvaluatorOptimizerLLM", "", text, flags=re.IGNORECASE)
        text = re.sub(r"search_finder", "", text, flags=re.IGNORECASE)
        text = re.sub(r"research_evaluator", "", text, flags=re.IGNORECASE)

        # Collapse excess whitespace
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        return text

    async def generate(
        self,
        message,  # type: ignore[override]
        request_params=None,  # type: ignore[override]
    ):
        # Call base implementation with a sanitized initial message to avoid leaking
        # planner/orchestrator agent references into the optimizer LLM user prompt.
        try:
            if isinstance(message, str):
                message = self._sanitize_request_text(message)
        except Exception:
            pass
        return await super().generate(message=message, request_params=request_params)

    def _build_eval_prompt(
        self, original_request: str, current_response: str, iteration: int
    ) -> str:
        """Build the evaluation prompt without inlining evaluator.instruction.

        The evaluator's full criteria live in the Agent instruction and are sent
        as a developer/system message by the underlying LLM implementation. To
        prevent duplication, we exclude those criteria here and focus the user
        message on the task context and the required output format.
        """
        return (
            "Evaluate the following response for quality.\n\n"
            f"Original Request: {original_request}\n"
            f"Current Response (Iteration {iteration + 1}): {current_response}\n\n"
            "Return a structured evaluation with:\n"
            "- rating\n"
            "- feedback\n"
            "- needs_improvement (true/false)\n"
            "- focus_areas (optional)\n"
        )

    def _build_refinement_prompt(
        self,
        original_request: str,
        current_response: str,
        feedback,
        iteration: int,
    ) -> str:
        """Build the refinement prompt without restating the original request text."""
        return (
            "Improve your previous response based on the evaluation feedback.\n\n"
            f"Previous Response (Iteration {iteration + 1}):\n{current_response}\n\n"
            f"Quality Rating: {feedback.rating}\n"
            f"Feedback: {feedback.feedback}\n"
            f"Areas to Focus On: {', '.join(getattr(feedback, 'focus_areas', []) or [])}\n\n"
            "Generate an improved version addressing the feedback while maintaining accuracy and relevance."
        )
