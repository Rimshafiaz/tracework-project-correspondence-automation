import pytest
from pydantic import ValidationError

from app.evaluation.datasets import DatasetManifest, DatasetSplit, DatasetStatus, dataset_directory


def test_development_and_held_out_datasets_are_separate() -> None:
    development_directory = dataset_directory(DatasetSplit.DEVELOPMENT)
    held_out_directory = dataset_directory(DatasetSplit.HELD_OUT)

    assert development_directory != held_out_directory
    for split, directory in (
        (DatasetSplit.DEVELOPMENT, development_directory),
        (DatasetSplit.HELD_OUT, held_out_directory),
    ):
        manifest = DatasetManifest.model_validate_json(
            (directory / "manifest.json").read_text(encoding="utf-8")
        )
        assert manifest.split is split
        assert manifest.status is DatasetStatus.EDITABLE
        assert manifest.content_hash is None
    assert len(
        DatasetManifest.model_validate_json(
            (development_directory / "manifest.json").read_text(encoding="utf-8")
        ).case_files
    ) == 3
    assert (
        DatasetManifest.model_validate_json(
            (held_out_directory / "manifest.json").read_text(encoding="utf-8")
        ).case_files
        == ()
    )


def test_frozen_dataset_requires_a_content_hash() -> None:
    with pytest.raises(ValidationError, match="requires a content hash"):
        DatasetManifest(
            schema_version="1",
            dataset_version="1.0.0",
            split=DatasetSplit.HELD_OUT,
            status=DatasetStatus.FROZEN,
        )


def test_editable_dataset_cannot_claim_a_frozen_hash() -> None:
    with pytest.raises(ValidationError, match="cannot claim"):
        DatasetManifest(
            schema_version="1",
            dataset_version="draft",
            split=DatasetSplit.HELD_OUT,
            status=DatasetStatus.EDITABLE,
            content_hash="sha256:example",
        )


def test_manifest_rejects_duplicate_case_files() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        DatasetManifest(
            schema_version="1",
            dataset_version="draft",
            split=DatasetSplit.DEVELOPMENT,
            status=DatasetStatus.EDITABLE,
            case_files=("case.json", "case.json"),
        )
