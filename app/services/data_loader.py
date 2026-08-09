import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, TypeAdapter, ValidationError

T = TypeVar("T", bound=BaseModel)


class DataLoadError(RuntimeError):
    pass


class JsonDataLoader:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def load(self, filename: str, model: type[T]) -> list[T]:
        path = self.data_dir / filename
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return TypeAdapter(list[model]).validate_python(raw)  # type: ignore[valid-type]
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise DataLoadError(f"Could not load valid data from {filename}") from exc
