import glob
import logging
import time
from collections.abc import Iterator

import mlx.core as mx
import mlx.nn as nn
from mlx_lm.sample_utils import categorical_sampling, min_p_sampling
from mlx_lm.utils import _get_classes, get_model_path, load_config
from pse.structure.engine import StructuringEngine

from agent.inference.frontend import FrontEnd
from agent.inference.utils.reuseable_cache import ReusableKVCache
from agent.inference.utils.tokenizer_wrapper import TokenizerWrapper

logger = logging.getLogger(__name__)


class MLXFrontEnd(FrontEnd):
    """
    Front-end for MLX models.
    """

    def __init__(self, model_path: str):
        """
        Initialize the MLXFrontEnd.

        Args:
            model_path (str): The path to the model.
        """
        self.load_model(model_path)
        self.initialize_cache(self.model)
        self.tokenizer = TokenizerWrapper.load(model_path, self.model_type)
        self.engine = StructuringEngine(self.tokenizer._tokenizer)
        self.computed_prompt_tokens = []

    def inference(self, prompt: list[int], **kwargs) -> Iterator[FrontEnd.ModelOutput]:
        """
        A generator producing token ids based on the given prompt from the model.

        Args:
            prompt (list[int]): The input prompt.
            **kwargs: Keyword arguments for the sampler.
        """
        if seed := kwargs.get("seed", None):
            mx.random.seed(seed)

        mlx_prompt = mx.array(prompt)
        if isinstance(self.cache[0], ReusableKVCache) and self.computed_prompt_tokens:
            tic = time.perf_counter()
            i = 0
            for i, t in enumerate(self.computed_prompt_tokens):
                if i >= len(mlx_prompt) - 1 or mlx_prompt[i] != t:
                    break
            for layer_cache in self.cache:
                assert isinstance(layer_cache, ReusableKVCache)
                layer_cache.reuse(len(mlx_prompt), i)
            logger.debug(f"Reusing KVCache for {i}/{len(mlx_prompt)} tokens")
            y = mlx_prompt[i:]
            mx.metal.clear_cache()
            toc = time.perf_counter()
            reuse_time = toc - tic
            logger.debug(f"Reuse time: {reuse_time:.4f}s")
        else:
            y = mlx_prompt

        if not self.computed_prompt_tokens:
            self.computed_prompt_tokens = prompt

        model_output = self.inference_step(y, **kwargs)
        y, logprobs = model_output.tokens, model_output.logprobs
        mx.async_eval(model_output.tokens, logprobs)
        mx.eval(y)

        while True:
            yield model_output
            new_model_output = self.inference_step(y, **kwargs)
            new_y, new_logprobs = new_model_output.tokens, new_model_output.logprobs
            mx.async_eval(new_y, new_logprobs)

            model_output = new_model_output
            y, logprobs = new_y, new_logprobs

    def inference_step(self, prompt: mx.array, **sampler_kwargs) -> FrontEnd.ModelOutput:
        """
        A single step of inference on the given prompt from the model.

        Args:
            prompt (mx.array): The input prompt.
            **sampler_kwargs: Keyword arguments for the sampler.
        returns:
            Result: The result of the generation step.
        """
        tic = time.perf_counter()
        logits = self.model(prompt[None], cache=self.cache)
        logits = logits[:, -1, :]
        assert isinstance(logits, mx.array)
        toc = time.perf_counter()
        inference_time = toc - tic
        logger.debug(f"Model inference time: {inference_time:.4f}s")

        engine_time = 0.0
        if self.engine:
            tic = time.perf_counter()
            logits = self.engine(logits[0, :])
            toc = time.perf_counter()
            engine_time = toc - tic
            logger.debug(f"Engine time: {engine_time:.4f}s")

        tic = time.perf_counter()
        logprobs = logits - mx.logsumexp(logits, keepdims=True)
        token_ids = (
            self.engine.sample(logprobs, self.sample_tokens, **sampler_kwargs)
            if self.engine
            else self.sample_tokens(logprobs, **sampler_kwargs).tolist()
        )
        assert isinstance(token_ids, list)
        self.computed_prompt_tokens.extend(token_ids)
        toc = time.perf_counter()
        sampling_time = toc - tic
        logger.debug(f"Sampling time: {sampling_time:.4f}s")

        return FrontEnd.ModelOutput(
            mx.array(token_ids, dtype=prompt.dtype),
            token_ids,
            logprobs,
            self.engine is not None and self.engine.is_within_value,
            inference_time,
            engine_time,
            sampling_time,
        )

    @staticmethod
    def sample_tokens(logprobs: mx.array, **kwargs) -> mx.array:
        """
        Sample tokens from the given logprobs.
        This function is used by the structuring engine.
        Easily extendable.

        Args:
            logprobs (mx.array): The logprobs to sample from.
            **kwargs: Keyword arguments for the sampler.
        Returns:
            mx.array: The sampled tokens.
        """
        temp = float(kwargs.get("temperature", 1.0))
        min_p = float(kwargs.get("min_p", 0.0))
        min_tokens_to_keep = int(kwargs.get("min_tokens_to_keep", 1))

        token: mx.array
        if min_p > 0.0:
            token = min_p_sampling(logprobs[None], min_p, min_tokens_to_keep, temp)
        elif temp > 0.0:
            token = categorical_sampling(logprobs[None], temp)
        else:
            token = mx.argmax(logprobs[None])

        return token

    def load_model(self, model_path: str) -> None:
        """
        Load and initialize the model from a given path.

        Args:
            model_path (Path): The path to load the model from.
        Returns:
            nn.Module: The loaded and initialized model.
        """
        self.run_configuration_script()
        path = get_model_path(model_path)
        config = load_config(path)
        model_type: str = config.get("model_type", "chatml")

        weight_files = glob.glob(str(path / "model*.safetensors"))
        if not weight_files:
            logging.error(f"No safetensors found in {path}")

        weights = {}
        for wf in weight_files:
            weights.update(mx.load(wf))

        model_class, model_args_class = _get_classes(config)
        model_args = model_args_class.from_dict(config)
        model = model_class(model_args)
        breakpoint()

        if hasattr(model, "sanitize"):
            weights = model.sanitize(weights)

        if (quantization := config.get("quantization", None)) is not None:
            nn.quantize(
                model,
                **quantization,
            )

        model.load_weights(list(weights.items()))
        mx.eval(model.parameters())
        model.eval()
        self.model = model
        self.model_type = model_type

    def initialize_cache(self, model: nn.Module) -> None:
        """
        Initialize the cache for the model.

        Args:
            model (nn.Module): The model for which to initialize the cache.
        """
        if model and hasattr(model, "make_cache"):
            self.cache = model.make_cache()  # type: ignore reportOptionalCall
        else:
            self.cache = ReusableKVCache.for_model(model)

    def run_configuration_script(self):
        """
        Shell script to configure the Apple Silicon memory settings.
        Shell script written by EXO Labs.
        """
        import os
        import subprocess

        file_name = "mlx.sh"
        try:
            file_path = os.path.join(os.path.dirname(__file__), file_name)
            subprocess.run(["bash", file_path], check=True)
        except Exception as e:
            logger.error(f"Failed to run configure script: {e}")
