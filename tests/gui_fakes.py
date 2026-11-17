# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""A stand-in engine and sample library so the interface can run without any models."""

from __future__ import annotations

import threading
import time
from collections.abc import Collection
from pathlib import Path

from istinbat.core import AskResult, AskStatus, IndexReport, Settings, Source, Stage, StageEvent
from istinbat.core.downloads import DownloadCancelled, DownloadProgress
from istinbat.core.history import ChatHistory
from istinbat.core.progress import Progress, ProgressKey

SAMPLE_ANSWERS = {
    "default": "المعلومات هي النتائج التي نحصل عليها من عملية معالجة البيانات.",
}
MARKDOWN_ANSWER_EN = """## Types of memory

A computer uses **several kinds** of memory, each with a different job:

1. `RAM` – fast, temporary working memory
2. *Storage* – slower, but it keeps data when the power is off
3. Cache – a tiny, very fast buffer next to the CPU

> Rule of thumb: the faster the memory, the smaller and more expensive it is.

| Type | Speed | Persistent |
|:-----|:-----:|-----------:|
| RAM | fast | no |
| SSD | medium | yes |

```python
import psutil
print(psutil.virtual_memory().total)
```

See the [Python docs](https://docs.python.org) for more."""

MARKDOWN_ANSWER_AR = """## أنواع الذاكرة

يستخدم الحاسوب **عدة أنواع** من الذاكرة، ولكل نوع وظيفته:

1. `RAM` – ذاكرة عمل سريعة ومؤقتة
2. *التخزين* – أبطأ لكنه يحفظ البيانات عند انقطاع الكهرباء
3. الذاكرة المخبئية – مخزن صغير وسريع جداً بجوار المعالج

> قاعدة عامة: كلما زادت سرعة الذاكرة قلّ حجمها وارتفع ثمنها.

| النوع | السرعة | دائمة |
|:-----|:-----:|-----:|
| RAM | سريعة | لا |
| SSD | متوسطة | نعم |

```bash
free -h
```"""

SAMPLE_PASSAGE = "تُعرَّف المعلومات بأنها بيانات جرت معالجتها وتنظيمها لتصبح ذات معنى يفيد من يستخدمها في اتخاذ القرار."
SAMPLE_BOOKS = ["أساسيات الحاسوب والبرمجيات", "مدخل إلى قواعد البيانات", "مبادئ الشبكات"]


class FakeEngine:
    """Answers every question with a canned Arabic answer and simulated stages (or a blocked answer)."""

    def __init__(
        self, settings: Settings, answer: str = SAMPLE_ANSWERS["default"], delay: float = 0.0, blocked: bool = False,
    ) -> None:
        self.settings = settings
        self.answer = answer
        self.delay = delay
        self.blocked = blocked          # Simulate an answer withheld by the safety check.
        self.asked: list[tuple[str, Collection[str] | None]] = []
        self.index_runs = 0
        self.rebuilds = 0
        self.loads = 0                  # How many times the engine factory ran (the models were loaded).

    def books(self) -> list[str]:
        return sorted(SAMPLE_BOOKS)

    def ask(self, question, history: ChatHistory | None = None, *, on_stage=None, on_token=None, cancel=None,
            books=None) -> AskResult:
        self.asked.append((question, books))
        result = AskResult(question=question, standalone=question)
        for stage in (Stage.VECTOR, Stage.BM25, Stage.RERANK, Stage.LLM):
            if on_stage:
                on_stage(stage, StageEvent.START, 0.0)
            time.sleep(self.delay)
            if cancel and cancel():
                result.status = AskStatus.CANCELLED
                return result
            result.timings[stage] = 1.25
            if on_stage:
                on_stage(stage, StageEvent.DONE, 1.25)
        for word in self.answer.split(" "):
            if cancel and cancel():
                result.status = AskStatus.CANCELLED
                return result
            if on_token:
                on_token(word + " ")
            time.sleep(self.delay)
        if self.blocked:
            result.status = AskStatus.BLOCKED
            return result
        result.answer = self.answer
        result.sources = [Source(SAMPLE_BOOKS[0], SAMPLE_PASSAGE, 0.9), Source(SAMPLE_BOOKS[1], SAMPLE_PASSAGE, 0.7)]
        if history is not None:
            history.add(question, self.answer)
        return result

    def index_library(self, progress=None, cancel=None) -> IndexReport:
        self.index_runs += 1
        if progress:
            progress(Progress(0.5, ProgressKey.INDEX_ENCODING, {"book": SAMPLE_BOOKS[0], "done": 5, "total": 10}))
            progress(Progress(1.0, ProgressKey.INDEX_DONE))
        return IndexReport(new_books=1)

    def rebuild_index(self, progress=None, cancel=None) -> IndexReport:
        self.rebuilds += 1
        return self.index_library(progress, cancel)


class FakeDownloader:
    """Pretends to download: reports some progress, then waits to be released, failed or cancelled."""

    def __init__(self):
        self.calls = []
        self.release = threading.Event()
        self.failure = None

    def __call__(self, option, models_dir, *, progress, cancel):
        self.calls.append((option.key, models_dir))
        progress(DownloadProgress(option.approx_bytes // 4, option.approx_bytes, option.files[0].path))
        while not self.release.is_set():
            if cancel():
                raise DownloadCancelled
            time.sleep(0.005)
        if self.failure:
            raise self.failure
        for file in option.files:
            target = Path(models_dir) / option.directory / file.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x")
        return option.local_path(models_dir)


def write_sample_library(settings: Settings) -> None:
    """Create a few small Arabic books in the configured books folder."""
    import os

    os.makedirs(settings.paths.books_dir, exist_ok=True)
    for index, name in enumerate(SAMPLE_BOOKS):
        with open(os.path.join(settings.paths.books_dir, f"{name}.txt"), "w", encoding="utf-8") as handle:
            handle.write("هذه جملة تجريبية طويلة بما يكفي لتكون جزءاً من كتاب. " * (40 + 25 * index))
