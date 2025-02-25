import json
import os

from pydantic import BaseModel


class RoleTokens(BaseModel):
    system: str
    assistant: str
    user: str
    tool: str


class ControlTokens(BaseModel):
    template_type: str
    begin_of_text: str
    end_of_message: str
    end_of_sequence: str
    user_start: str
    user_end: str
    assistant_header_start: str
    assistant_header_end: str
    tool_start: str
    tool_end: str
    tool_result_start: str
    tool_result_end: str
    roles: RoleTokens

    def end_tokens(self) -> list[str]:
        return [self.end_of_sequence, self.end_of_message]

    def tool_use_delimiters(self) -> tuple[str, str] | None:
        if self.tool_start and self.tool_end:
            return self.tool_start, self.tool_end
        return None


def get_control_tokens(model_type: str) -> ControlTokens:
    """Get the control tokens for the model."""
    match model_type:
        case "llama":
            return _load_control_tokens("llama")
        case "llama-deepseek":
            return _load_control_tokens("llama-deepseek")
        case "mistral":
            return _load_control_tokens("mistral")
        case "deepseek":
            return _load_control_tokens("deepseek")
        case _:
            return _load_control_tokens("chatml")


def _load_control_tokens(model_type: str) -> ControlTokens:
    """Load the control tokens for the model."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_dir, f"{model_type}.json")
    with open(file_path) as f:
        data = json.load(f)
        return ControlTokens(**data)
