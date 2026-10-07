from unittest.mock import MagicMock

import pytest

from app.adapters.drive.client import GoogleDriveClient, sanitize_drive_name


def _service_with_list(files):
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {
        "files": files
    }
    return service


def test_folder_lookup_reuses_managed_folder_without_create():
    service = _service_with_list([{"id": "folder-1", "name": "Tracework"}])
    client = GoogleDriveClient(service)

    folder_id = client.ensure_folder(
        name="Tracework",
        parent_folder_id=None,
        app_properties={"tracework_scope": "root"},
    )

    assert folder_id == "folder-1"
    service.files.return_value.create.assert_not_called()


def test_missing_folder_is_created_with_deterministic_metadata():
    service = _service_with_list([])
    service.files.return_value.create.return_value.execute.return_value = {
        "id": "folder-2"
    }
    client = GoogleDriveClient(service)

    folder_id = client.ensure_folder(
        name="TW-001 - Project",
        parent_folder_id="root-1",
        app_properties={"tracework_project_id": "project-1"},
    )

    assert folder_id == "folder-2"
    body = service.files.return_value.create.call_args.kwargs["body"]
    assert body["parents"] == ["root-1"]
    assert body["appProperties"] == {"tracework_project_id": "project-1"}


def test_existing_file_is_found_by_managed_metadata():
    service = _service_with_list(
        [{"id": "file-1", "name": "report.pdf", "parents": ["folder-1"]}]
    )
    client = GoogleDriveClient(service)

    result = client.find_file(
        parent_folder_id="folder-1",
        app_properties={"tracework_document_id": "document-1"},
    )

    assert result is not None
    assert result.file_id == "file-1"


def test_duplicate_managed_items_fail_instead_of_picking_one():
    service = _service_with_list(
        [
            {"id": "one", "name": "one"},
            {"id": "two", "name": "two"},
        ]
    )

    with pytest.raises(RuntimeError, match="duplicate managed items"):
        GoogleDriveClient(service).ensure_folder(
            name="Tracework",
            parent_folder_id=None,
            app_properties={"tracework_scope": "root"},
        )


def test_drive_name_sanitization_is_deterministic_and_project_agnostic():
    assert sanitize_drive_name("  TW-001 / Example\\Project  ") == (
        "TW-001 - Example-Project"
    )
