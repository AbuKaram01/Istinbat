# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Discovery and loading of book files (plain ``.txt`` files)."""

from __future__ import annotations

import os
from dataclasses import dataclass

BOOK_EXTENSION = ".txt"


def book_name(path: str) -> str:
    """Return a book's display name: its file name without the extension."""
    return os.path.splitext(os.path.basename(path))[0]


@dataclass(frozen=True)
class BookFile:
    path: str
    content: str

    @property
    def name(self) -> str:
        return book_name(self.path)


def load_book_files(books_dir: str) -> list[BookFile]:
    """Read every ``.txt`` file below ``books_dir``; unreadable files are skipped."""
    books: list[BookFile] = []
    for root, directories, file_names in os.walk(books_dir):
        directories.sort()
        for file_name in sorted(file_names):
            if not file_name.endswith(BOOK_EXTENSION):
                continue
            path = os.path.join(root, file_name)
            try:
                with open(path, encoding="utf-8", errors="ignore") as handle:
                    books.append(BookFile(path, handle.read()))
            except OSError:
                continue
    return books
