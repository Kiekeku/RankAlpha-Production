from typing import List, Union

from mcp.types import PromptMessage
from mcp_agent.workflows.llm.augmented_llm import ModelT, RequestParams
from mcp_agent.workflows.llm.augmented_llm_openai import OpenAIAugmentedLLM
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionUserMessageParam,
)


class Gpt5PlannerLLM(OpenAIAugmentedLLM):
    """LLM wrapper that ensures GPT‑5 receives exactly one developer message and no system message.

    Implementation detail:
    - Temporarily suppress self.instruction while calling the base class to prevent system prompt injection.
    - Prepend a single developer message with the original instruction to the outgoing messages.
    """

    def _wrap_with_developer(
        self,
        message: Union[
            str,
            ChatCompletionMessageParam,
            PromptMessage,
            List[Union[str, ChatCompletionMessageParam, PromptMessage]],
        ],
        instruction: str | None,
    ) -> List[ChatCompletionMessageParam]:
        msgs: List[ChatCompletionMessageParam] = []
        if isinstance(message, list):
            for item in message:
                if isinstance(item, dict):
                    msgs.append(item)
                elif isinstance(item, PromptMessage):
                    role = getattr(item, "role", "user")
                    content = getattr(item, "content", "")
                    msgs.append({"role": role, "content": content})
                else:
                    msgs.append(ChatCompletionUserMessageParam(role="user", content=str(item)))
        elif isinstance(message, dict):
            msgs.append(message)
        elif isinstance(message, PromptMessage):
            role = getattr(message, "role", "user")
            content = getattr(message, "content", "")
            msgs.append({"role": role, "content": content})
        else:
            msgs.append(ChatCompletionUserMessageParam(role="user", content=str(message)))

        # Insert a single developer message up front if not already present
        if instruction:
            if not msgs or msgs[0].get("role") != "developer":
                dev: ChatCompletionMessageParam = {
                    "role": "developer",
                    "content": instruction,
                }
                msgs.insert(0, dev)
        return msgs

    async def generate(
        self,
        message: Union[
            str,
            ChatCompletionMessageParam,
            PromptMessage,
            List[Union[str, ChatCompletionMessageParam, PromptMessage]],
        ],
        request_params: RequestParams | None = None,
    ):
        # For GPT‑5, inject a single developer message via history and avoid system prompt
        if (
            request_params
            and request_params.model
            and str(request_params.model).lower().startswith("gpt-5")
        ):
            # Suppress system prompt injection by clearing instruction temporarily
            old_instruction = self.instruction
            self.instruction = None
            try:
                wrapped = self._wrap_with_developer(message, old_instruction)
                return await super().generate(message=wrapped, request_params=request_params)
            finally:
                self.instruction = old_instruction
        else:
            return await super().generate(message=message, request_params=request_params)

    async def generate_str(
        self,
        message: Union[
            str,
            ChatCompletionMessageParam,
            PromptMessage,
            List[Union[str, ChatCompletionMessageParam, PromptMessage]],
        ],
        request_params: RequestParams | None = None,
    ) -> str:
        if (
            request_params
            and request_params.model
            and str(request_params.model).lower().startswith("gpt-5")
        ):
            old_instruction = self.instruction
            self.instruction = None
            try:
                wrapped = self._wrap_with_developer(message, old_instruction)
                return await super().generate_str(message=wrapped, request_params=request_params)
            finally:
                self.instruction = old_instruction
        else:
            return await super().generate_str(message=message, request_params=request_params)

    async def generate_structured(
        self,
        message: Union[
            str,
            ChatCompletionMessageParam,
            PromptMessage,
            List[Union[str, ChatCompletionMessageParam, PromptMessage]],
        ],
        response_model: type[ModelT],
        request_params: RequestParams | None = None,
    ) -> ModelT:
        if (
            request_params
            and request_params.model
            and str(request_params.model).lower().startswith("gpt-5")
        ):
            old_instruction = self.instruction
            self.instruction = None
            try:
                wrapped = self._wrap_with_developer(message, old_instruction)
                return await super().generate_structured(
                    message=wrapped, response_model=response_model, request_params=request_params
                )
            finally:
                self.instruction = old_instruction
        else:
            return await super().generate_structured(
                message=message, response_model=response_model, request_params=request_params
            )
