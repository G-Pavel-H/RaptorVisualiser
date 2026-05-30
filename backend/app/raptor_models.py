"""RAPTOR model subclasses that meter every OpenAI call.

Each call:
  1. Acquires the global concurrency slot.
  2. Hits OpenAI with the cheap model variants (gpt-4o-mini / 3-small).
  3. Records prompt + completion tokens against the build's IP.

The recorder callback is bound per-build so each model knows whose budget
to debit. RAPTOR instantiates one set of these per build.
"""
from __future__ import annotations

from typing import Callable, Optional

from openai import OpenAI
from raptor.EmbeddingModels import BaseEmbeddingModel
from raptor.QAModels import BaseQAModel
from raptor.SummarizationModels import BaseSummarizationModel
from tenacity import retry, stop_after_attempt, wait_random_exponential

from . import cost_tracker

# Recorder signature: (model_name, prompt_tokens, completion_tokens) -> None
Recorder = Callable[[str, int, int], None]

EMBEDDING_MODEL = "text-embedding-3-small"
CHAT_MODEL = "gpt-4o-mini"


class TrackingEmbeddingModel(BaseEmbeddingModel):
    def __init__(self, recorder: Recorder, model: str = EMBEDDING_MODEL) -> None:
        self.model = model
        self._recorder = recorder
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI()
        return self._client

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def create_embedding(self, text):
        text = (text or "").replace("\n", " ")
        cost_tracker.acquire_slot()
        try:
            resp = self._get_client().embeddings.create(input=[text], model=self.model)
        finally:
            cost_tracker.release_slot()
        # Embedding responses only carry total_tokens — bill it as input.
        total = getattr(resp.usage, "total_tokens", 0) if resp.usage else 0
        self._recorder(self.model, total, 0)
        return resp.data[0].embedding


class TrackingSummarizationModel(BaseSummarizationModel):
    def __init__(self, recorder: Recorder, model: str = CHAT_MODEL) -> None:
        self.model = model
        self._recorder = recorder
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI()
        return self._client

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def summarize(self, context, max_tokens=150, stop_sequence=None):
        cost_tracker.acquire_slot()
        try:
            resp = self._get_client().chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {
                        "role": "user",
                        "content": (
                            "Write a concise summary of the following, retaining "
                            f"as many key details as possible: {context}"
                        ),
                    },
                ],
                max_tokens=max_tokens,
            )
        finally:
            cost_tracker.release_slot()
        usage = resp.usage
        self._recorder(
            self.model,
            getattr(usage, "prompt_tokens", 0) if usage else 0,
            getattr(usage, "completion_tokens", 0) if usage else 0,
        )
        return resp.choices[0].message.content


class TrackingQAModel(BaseQAModel):
    def __init__(self, recorder: Recorder, model: str = CHAT_MODEL) -> None:
        self.model = model
        self._recorder = recorder
        self._client: Optional[OpenAI] = None

    def _get_client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI()
        return self._client

    @retry(wait=wait_random_exponential(min=1, max=20), stop=stop_after_attempt(6))
    def answer_question(self, context, question, max_tokens=200, stop_sequence=None):
        cost_tracker.acquire_slot()
        try:
            resp = self._get_client().chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Answer using only the provided context."},
                    {
                        "role": "user",
                        "content": (
                            f"Context:\n{context}\n\nQuestion: {question}\n\n"
                            "Answer concisely."
                        ),
                    },
                ],
                max_tokens=max_tokens,
                temperature=0,
                stop=stop_sequence,
            )
        finally:
            cost_tracker.release_slot()
        usage = resp.usage
        self._recorder(
            self.model,
            getattr(usage, "prompt_tokens", 0) if usage else 0,
            getattr(usage, "completion_tokens", 0) if usage else 0,
        )
        return resp.choices[0].message.content.strip()
