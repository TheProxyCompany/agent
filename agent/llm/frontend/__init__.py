from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

from pse.engine.structuring_engine import StructuringEngine

from agent.llm.tokenizer import Tokenizer

T = TypeVar("T")


class Frontend(ABC):
    """
    Abstract base class for front-ends.
    """

    engine: StructuringEngine
    tokenizer: Tokenizer

    @staticmethod
    def from_path(model_path: str, frontend: str | None = "mlx") -> Frontend:
        if frontend == "mlx":
            from agent.llm.frontend.mlx import MLXInference

            return MLXInference(model_path)
        else:
            raise ValueError(f"Invalid front-end type: {frontend:}")

    def __call__(self, prompt: list[int], **kwargs) -> Iterator[int]:
        return self.inference(prompt, **kwargs)

    @abstractmethod
    def inference(self, prompt: list[int], **kwargs: Any) -> Iterator[int]:
        pass

    @abstractmethod
    def make_sampler(self, structured: bool, **kwargs) -> Callable[..., Any]:
        pass
