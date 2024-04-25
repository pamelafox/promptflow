# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------
import json
from dataclasses import dataclass
from typing import Any, Iterator, Mapping

from promptflow.executor._result import LineResult


class Row(Mapping[str, Any]):
    """Row data class."""

    def __init__(self, source: Mapping[str, Any], row_number: int = None):
        self._source = source
        self._rn = row_number

    @property
    def row_number(self) -> int:
        return int(self.get("line_number", self._rn))

    @classmethod
    def from_json(cls, json_str: str, **kwargs) -> "Row":
        return cls.from_dict(d=json.loads(json_str), **kwargs)

    @staticmethod
    def from_dict(d: Mapping[str, Any], row_number: int = None) -> "Row":
        return Row(source=d, row_number=row_number)

    def __getitem__(self, __k: str) -> Any:
        return self._source.__getitem__(__k)

    def __len__(self) -> int:
        return self._source.__len__()

    def __iter__(self) -> Iterator[str]:
        return self._source.__iter__()


@dataclass
class Result:
    input: Row
    output: LineResult