"""Where projects live."""

from __future__ import annotations

import json
import os
import pathlib
import re
import uuid
from datetime import datetime, timezone

from app.models.project import (
    PROJECT_SCHEMA_VERSION,
    ProjectDocument,
    ProjectState,
    ProjectSummary,
    StaleReport,
)
from app.services.project_revisions import apply_revisions, stale_report


class ProjectNotFound(LookupError):
    """No project with that id."""


class ProjectSchemaTooNew(ValueError):
    """The stored document was written by a later version of Fabrivium."""


def _now() -> str:
    # Microseconds, always present: the recent-projects list is sorted on
    # this string, and two projects created in the same second would
    # otherwise order arbitrarily.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def default_project_root() -> pathlib.Path:
    """Where projects are stored."""
    override = os.environ.get("FACTORYMIND_PROJECT_DIR")
    if override:
        return pathlib.Path(override)
    return pathlib.Path(__file__).resolve().parents[3] / "projects"


class ProjectStore:
    """Create, read, update and list projects."""

    def __init__(self, root: pathlib.Path | str | None = None) -> None:
        self._root = pathlib.Path(root) if root is not None else None

    @property
    def root(self) -> pathlib.Path:
        # Resolved per access rather than in __init__ so that setting
        # FACTORYMIND_PROJECT_DIR inside a test takes effect on the module
        # level store, which is created at import time.
        root = self._root or default_project_root()
        root.mkdir(parents=True, exist_ok=True)
        return root

    # Paths

    def _path(self, project_id: str) -> pathlib.Path:
        if not _SAFE_ID.match(project_id):
            # Ids are minted here, so anything else arrived from a URL.
            raise ProjectNotFound(f"'{project_id}' is not a project id.")
        return self.root / f"{project_id}.json"

    # Commands

    def create(self, name: str, state: ProjectState | None = None) -> ProjectDocument:
        """A new, empty, named project."""
        clean = name.strip()
        if not clean:
            raise ValueError("A project needs a name.")

        stamped = _now()
        document = ProjectDocument(
            schema_version=PROJECT_SCHEMA_VERSION,
            project_id=uuid.uuid4().hex[:16],
            name=clean,
            created_at=stamped,
            updated_at=stamped,
            state=apply_revisions(None, state or ProjectState()),
        )
        self._write(document)
        return document

    def save(self, project_id: str, state: ProjectState, name: str | None = None) -> ProjectDocument:
        """Store new state for an existing project."""
        existing = self.load(project_id)
        merged = apply_revisions(existing.state, state)
        document = existing.model_copy(
            update={
                "name": (name.strip() if name and name.strip() else existing.name),
                "updated_at": _now(),
                "state": merged,
            }
        )
        self._write(document)
        return document

    def delete(self, project_id: str) -> None:
        path = self._path(project_id)
        if not path.exists():
            raise ProjectNotFound(f"There is no project '{project_id}'.")
        path.unlink()

    # Queries

    def load(self, project_id: str) -> ProjectDocument:
        path = self._path(project_id)
        if not path.exists():
            raise ProjectNotFound(f"There is no project '{project_id}'.")
        return self._read(path)

    def list_projects(self) -> list[ProjectSummary]:
        """Every readable project, most recently updated first."""
        summaries: list[ProjectSummary] = []
        for path in self.root.glob("*.json"):
            try:
                document = self._read(path)
            except Exception:  # noqa: BLE001 - see docstring
                continue
            summaries.append(
                ProjectSummary(
                    project_id=document.project_id,
                    name=document.name,
                    created_at=document.created_at,
                    updated_at=document.updated_at,
                    product_name=document.state.product.name,
                    is_example=document.state.is_example,
                )
            )
        summaries.sort(key=lambda s: s.updated_at, reverse=True)
        return summaries

    @staticmethod
    def staleness(document: ProjectDocument) -> StaleReport:
        """What in this project may no longer be shown as current."""
        return stale_report(document.state)

    # Io

    def _read(self, path: pathlib.Path) -> ProjectDocument:
        raw = json.loads(path.read_text(encoding="utf-8"))
        version = raw.get("schema_version", 0)
        if version > PROJECT_SCHEMA_VERSION:
            raise ProjectSchemaTooNew(
                f"'{path.name}' was written by a newer version of Fabrivium "
                f"(schema {version}; this build reads {PROJECT_SCHEMA_VERSION})."
            )
        return ProjectDocument.model_validate(raw)

    def _write(self, document: ProjectDocument) -> None:
        path = self._path(document.project_id)
        # Same directory, so the replace below is a rename rather than a
        # cross-device copy — the property the atomicity depends on.
        temporary = path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
        payload = document.model_dump_json(indent=2)
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():  # pragma: no cover - only on a failed write
                temporary.unlink(missing_ok=True)


# The application's store.
project_store = ProjectStore()
