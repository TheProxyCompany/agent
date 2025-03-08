import json
import os

from pydantic import BaseModel


class RoleTokens(BaseModel):
    system: str
    assistant: str
    user: str
    tool: str


class ControlTokens(BaseModel):
    """Control tokens for different model templates.

    This class defines the structure and access methods for control tokens used in
    various LLM template formats.
    """
    template_type: str
    begin_of_text: str
    end_of_message: str
    end_of_sequence: str
    user_start: str
    user_end: str
    assistant_header_start: str
    assistant_header_end: str
    inner_monologue_start: str | None = None
    inner_monologue_end: str | None = None
    thinking_start: str | None = None
    thinking_end: str | None = None
    scratchpad_start: str | None = None
    scratchpad_end: str | None = None
    reasoning_start: str | None = None
    reasoning_end: str | None = None
    tool_list_start: str | None = None
    tool_list_end: str | None = None
    tool_start: str
    tool_end: str
    tool_result_start: str
    tool_result_end: str
    roles: RoleTokens

    def delimiters(self) -> dict[str, tuple[str, str] | None]:
        """Returns a dictionary of all delimiter pairs.

        Returns:
            A dictionary mapping state names to their delimiter tuples.
        """
        return {
            "inner_monologue": self.inner_monologue_delimiters,
            "reasoning": self.reasoning_delimiters,
            "scratchpad": self.scratchpad_delimiters,
            "thinking": self.thinking_delimiters,
            "tool_call": self.tool_use_delimiters,
            "tool_list": self.tool_list_delimiters,
            "tool_result": self.tool_result_delimiters,
        }

    def end_tokens(self) -> list[str]:
        """Returns a list of tokens that indicate the end of a sequence.

        Returns:
            A list of end tokens.
        """
        return [self.end_of_sequence, self.end_of_message]

    def get_whitelist_control_tokens(self) -> list[str]:
        """Returns the control tokens used for tokenization.

        Returns:
            A list of the most essential control tokens.
        """
        tokens: list[str] = []
        for delim in self.delimiters().values():
            if delim:
                start, end = delim
                if start.strip():
                    tokens.append(start.strip())
                if end.strip():
                    tokens.append(end.strip())

        return tokens

    @property
    def inner_monologue_delimiters(self) -> tuple[str, str] | None:
        """Returns the inner monologue delimiter pair if defined.

        Returns:
            A tuple of start and end delimiters, or None if not defined.
        """
        if self.inner_monologue_start and self.inner_monologue_end:
            return self.inner_monologue_start, self.inner_monologue_end
        return None

    @property
    def reasoning_delimiters(self) -> tuple[str, str] | None:
        """Returns the reasoning delimiter pair if defined.

        Returns:
            A tuple of start and end delimiters, or None if not defined.
        """
        if self.reasoning_start and self.reasoning_end:
            return self.reasoning_start, self.reasoning_end
        return None

    @property
    def scratchpad_delimiters(self) -> tuple[str, str] | None:
        """Returns the scratchpad delimiter pair if defined.

        Returns:
            A tuple of start and end delimiters, or None if not defined.
        """
        if self.scratchpad_start and self.scratchpad_end:
            return self.scratchpad_start, self.scratchpad_end
        return None

    @property
    def thinking_delimiters(self) -> tuple[str, str] | None:
        """Returns the thinking delimiter pair if defined.

        Returns:
            A tuple of start and end delimiters, or None if not defined.
        """
        if self.thinking_start and self.thinking_end:
            return self.thinking_start, self.thinking_end
        return None

    @property
    def tool_list_delimiters(self) -> tuple[str, str] | None:
        """Returns the tool list delimiter pair if defined.

        Returns:
            A tuple of start and end delimiters, or None if not defined.
        """
        if self.tool_list_start and self.tool_list_end:
            return self.tool_list_start, self.tool_list_end
        return None

    @property
    def tool_result_delimiters(self) -> tuple[str, str] | None:
        """Returns the tool result delimiter pair if defined.

        Returns:
            A tuple of start and end delimiters, or None if not defined.
        """
        if self.tool_result_start and self.tool_result_end:
            return self.tool_result_start, self.tool_result_end
        return None

    @property
    def tool_use_delimiters(self) -> tuple[str, str] | None:
        """Returns the tool use delimiter pair if defined.

        Returns:
            A tuple of start and end delimiters, or None if not defined.
        """
        if self.tool_start and self.tool_end:
            return self.tool_start, self.tool_end
        return None


def get_control_tokens(model_path: str, tokenizer_config: dict) -> ControlTokens:
    """Get the control tokens for the model."""
    model_type = _determine_model_type(model_path, tokenizer_config)
    match model_type:
        case "llama":
            return _load_control_tokens("llama")
        case "llama-deepseek":
            return _load_control_tokens("llama-deepseek")
        case "mistral":
            return _load_control_tokens("mistral")
        case "deepseek":
            return _load_control_tokens("deepseek")
        case "hermes":
            return _load_control_tokens("hermes")
        case _:
            return _load_control_tokens("chatml")


def _determine_model_type(model_path: str, tokenizer_config: dict) -> str:
    """Determine the model type from the model path."""
    model_type = tokenizer_config.get("model_type", "chatml")
    eos_token = tokenizer_config.get("eos_token", "<|eot_id|>")
    if eos_token == "<|eot_id|>":
        model_type = "llama"
    elif eos_token.strip() == "<|im_end|>":
        model_type = "chatml"

    if model_type == "llama":
        if "deepseek" in model_path.lower():
            model_type = "llama-deepseek"
    elif model_type == "chatml" and "hermes" in model_path.lower():
        model_type = "hermes"

    return model_type


def _load_control_tokens(model_type: str) -> ControlTokens:
    """Load the control tokens for the model."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_dir, f"{model_type}.json")
    with open(file_path) as f:
        data = json.load(f)
        return ControlTokens(**data)
