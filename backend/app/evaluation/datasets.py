from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, model_validator

from app.evaluation.contracts import EvaluationCase


class DatasetSplit(StrEnum):
    DEVELOPMENT = "development"
    HELD_OUT = "held_out"


class DatasetStatus(StrEnum):
    EDITABLE = "editable"
    FROZEN = "frozen"


class DatasetManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: str
    dataset_version: str
    split: DatasetSplit
    status: DatasetStatus
    case_files: tuple[str, ...] = ()
    content_hash: str | None = None

    @model_validator(mode="after")
    def validate_freeze_metadata(self) -> "DatasetManifest":
        if self.status is DatasetStatus.FROZEN and not self.content_hash:
            raise ValueError("a frozen dataset requires a content hash")
        if self.status is DatasetStatus.EDITABLE and self.content_hash is not None:
            raise ValueError("an editable dataset cannot claim a frozen content hash")
        if len(self.case_files) != len(set(self.case_files)):
            raise ValueError("case file names must be unique")
        return self


DATASET_ROOT = Path(__file__).resolve().parents[2] / "evaluation_data"


def dataset_directory(split: DatasetSplit) -> Path:
    return DATASET_ROOT / split.value


def load_manifest(split: DatasetSplit) -> DatasetManifest:
    path = dataset_directory(split) / "manifest.json"
    manifest = DatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))
    if manifest.split is not split:
        raise ValueError("manifest split does not match its dataset directory")
    return manifest


def load_case(path: Path) -> EvaluationCase:
    return EvaluationCase.model_validate_json(path.read_text(encoding="utf-8"))


def load_dataset(split: DatasetSplit) -> tuple[EvaluationCase, ...]:
    directory = dataset_directory(split).resolve()
    manifest = load_manifest(split)
    cases = []
    for filename in manifest.case_files:
        path = (directory / filename).resolve()
        if path.parent != directory:
            raise ValueError("case files must be direct children of the dataset directory")
        cases.append(load_case(path))
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("case IDs must be unique within a dataset")
    return tuple(cases)
