"""Thin, uniform wrapper over the DataHub SDK calls Blastradar depends on.

Why this layer exists:
  * one place per network call, so every call site is uniform;
  * every method returns plain JSON-able dicts/lists (never SDK objects), so Phase 2
    can record them to fixtures and replay them verbatim;
  * an optional ``observer`` is invoked after each call with ``(method, kwargs, result)``
    — that is the record hook Phase 2 plugs into;
  * transient network failures are retried with exponential backoff;
  * every call is logged at DEBUG with its arguments.

Only the calls verified in docs/API-NOTES.md are used. Connection is tokenless-friendly
(local quickstart runs with auth disabled); a token is used when present.
"""

from __future__ import annotations

import logging
import os
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import datahub.metadata.schema_classes as M
from datahub.emitter.mcp import MetadataChangeProposalWrapper
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, Timeout

from blastradar.datahub.urns import dataset_name, dataset_platform

logger = logging.getLogger(__name__)

DEFAULT_SERVER = "http://localhost:8080"
_URL_KEYS = ("DATAHUB_GMS_URL", "DATAHUB_GMS_HOST", "DATAHUB_SERVER")
_TOKEN_KEYS = ("DATAHUB_GMS_TOKEN", "DATAHUB_TOKEN")
_TRANSIENT = (RequestsConnectionError, Timeout, HTTPError, ConnectionError, TimeoutError)


class DataHubClientError(Exception):
    """Raised when a DataHub call fails after exhausting retries."""


class CallObserver(Protocol):
    """Record hook: called after each successful client method (Phase 2 fixtures)."""

    def __call__(self, method: str, kwargs: dict[str, Any], result: Any) -> None: ...


@dataclass(frozen=True)
class ClientConfig:
    """Connection settings for the wrapper."""

    server: str = DEFAULT_SERVER
    token: str | None = None


def _load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines from a .env into os.environ (does not overwrite)."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def config_from_env(*, dotenv: Path | None = None) -> ClientConfig:
    """Build a :class:`ClientConfig` from ``.env`` / environment (token optional)."""
    if dotenv is None:
        dotenv = Path(__file__).resolve().parents[3] / ".env"
    _load_dotenv(dotenv)
    server = next((os.environ[k] for k in _URL_KEYS if os.environ.get(k)), DEFAULT_SERVER)
    token = next((os.environ[k] for k in _TOKEN_KEYS if os.environ.get(k)), None)
    if not token:
        logger.debug("No DataHub token found — connecting tokenless (auth disabled).")
    return ClientConfig(server=server, token=token)


class DataHubClient:
    """Uniform, recordable, retrying facade over the DataHub SDK."""

    def __init__(
        self,
        config: ClientConfig | None = None,
        *,
        observer: CallObserver | None = None,
        retries: int = 3,
        backoff: float = 0.5,
    ) -> None:
        self._config = config or ClientConfig()
        self._observer = observer
        self._retries = max(1, retries)
        self._backoff = backoff
        self._sdk: Any = None
        self._graph: Any = None

    # -- construction ----------------------------------------------------- #
    @classmethod
    def from_env(cls, **kwargs: Any) -> DataHubClient:
        """Construct from ``.env`` / environment settings.

        If ``BLASTRADAR_REPLAY`` names a recording file, a
        :class:`~blastradar.datahub.replay.ReplayClient` is returned instead — the
        whole pipeline then runs offline against recorded fixtures (``make demo``),
        with no DataHub, network, or credentials. See ``datahub/replay.py``.
        """
        replay_path = os.environ.get("BLASTRADAR_REPLAY")
        if replay_path:
            from blastradar.datahub.replay import ReplayClient  # lazy: avoid import cycle
            logger.info("BLASTRADAR_REPLAY set — serving DataHub calls from %s", replay_path)
            return ReplayClient.from_file(replay_path, **kwargs)
        return cls(config_from_env(), **kwargs)

    def _ensure(self) -> None:
        if self._sdk is not None:
            return
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # datahub.sdk ExperimentalWarning
            from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig
            from datahub.sdk import DataHubClient as _SdkClient
        cfg = DatahubClientConfig(server=self._config.server, token=self._config.token)
        self._graph = DataHubGraph(cfg)
        self._sdk = _SdkClient(server=self._config.server, token=self._config.token)

    # -- call plumbing ---------------------------------------------------- #
    def _call(self, method: str, fn: Callable[[], Any], **kwargs: Any) -> Any:
        """Run a network call with DEBUG logging, retry/backoff, and the observer hook."""
        self._ensure()
        logger.debug("datahub.%s args=%s", method, kwargs)
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                result = fn()
                break
            except _TRANSIENT as e:  # transient — retry with backoff
                last = e
                if attempt == self._retries - 1:
                    raise DataHubClientError(
                        f"{method} failed after {self._retries} attempts: {e}"
                    ) from e
                sleep = self._backoff * (2**attempt)
                logger.warning("datahub.%s transient error (attempt %d): %s; retrying in %.1fs",
                               method, attempt + 1, e, sleep)
                time.sleep(sleep)
        else:  # pragma: no cover - loop always breaks or raises
            raise DataHubClientError(f"{method} failed: {last}")
        if self._observer is not None:
            self._observer(method, kwargs, result)
        return result

    # -- reads (all return JSON-able structures) -------------------------- #
    def test_connection(self) -> None:
        """Raise if the GMS is unreachable."""
        self._call("test_connection", lambda: self._sdk.test_connection())

    def get_lineage(
        self,
        urn: str,
        *,
        column: str | None = None,
        direction: str = "downstream",
        max_hops: int = 1,
        count: int = 500,
    ) -> list[dict]:
        """One lineage query. Column-constrained when ``column`` is given.

        Returns dicts: ``{urn, type, hops, direction, name, platform, paths:[{urn,
        entity_name, column_name}]}``. Per API-NOTES: column-constrained lineage does
        NOT reach mlFeatures — use table-level (``column=None``) for dataset->feature.
        """
        def run() -> list[dict]:
            results = self._sdk.lineage.get_lineage(
                source_urn=urn, source_column=column, direction=direction,
                max_hops=max_hops, count=count,
            )
            out = []
            for r in results:
                paths = [
                    {"urn": getattr(p, "urn", None), "entity_name": p.entity_name,
                     "column_name": p.column_name}
                    for p in (r.paths or [])
                ]
                out.append({"urn": r.urn, "type": r.type, "hops": r.hops,
                            "direction": r.direction, "name": r.name,
                            "platform": r.platform, "paths": paths})
            return out
        return self._call("get_lineage", run, urn=urn, column=column,
                          direction=direction, max_hops=max_hops)

    def get_schema_fields(self, dataset_urn: str) -> list[dict]:
        """List a dataset's schema fields: ``[{field_path, native_type, is_key}]``."""
        def run() -> list[dict]:
            sm = self._graph.get_schema_metadata(dataset_urn)
            if not sm or not sm.fields:
                return []
            return [{"field_path": f.fieldPath, "native_type": f.nativeDataType,
                     "is_key": bool(f.isPartOfKey)} for f in sm.fields]
        return self._call("get_schema_fields", run, dataset_urn=dataset_urn)

    def search_datasets(self, query: str, *, count: int = 100) -> list[dict]:
        """Search datasets by name: ``[{urn, platform, name}]`` (fuzzy; caller ranks)."""
        def run() -> list[dict]:
            urns = self._graph.get_urns_by_filter(
                entity_types=["dataset"], query=query, batch_size=count)
            return [{"urn": u, "platform": dataset_platform(u), "name": dataset_name(u)}
                    for u in urns]
        return self._call("search_datasets", run, query=query)

    def get_ml_model(self, urn: str) -> dict | None:
        """Read MLModelProperties: name/version/mlFeatures/deployments/trainingJobs/groups."""
        def run() -> dict | None:
            mp = self._graph.get_aspect(urn, M.MLModelPropertiesClass)
            if mp is None:
                return None
            return {
                "urn": urn, "name": mp.name,
                "version": mp.version.versionTag if mp.version else None,
                "ml_features": list(mp.mlFeatures or []),
                "deployments": list(mp.deployments or []),
                "training_jobs": list(mp.trainingJobs or []),
                "groups": list(mp.groups or []),
            }
        return self._call("get_ml_model", run, urn=urn)

    def get_ml_feature(self, urn: str) -> dict | None:
        """Read MLFeatureProperties: sources + customProperties (incl. source column)."""
        def run() -> dict | None:
            fp = self._graph.get_aspect(urn, M.MLFeaturePropertiesClass)
            if fp is None:
                return None
            return {"urn": urn, "sources": list(fp.sources or []),
                    "custom_properties": dict(fp.customProperties or {}),
                    "description": fp.description}
        return self._call("get_ml_feature", run, urn=urn)

    def get_deployment(self, urn: str) -> dict | None:
        """Read MLModelDeploymentProperties: status + description."""
        def run() -> dict | None:
            dp = self._graph.get_aspect(urn, M.MLModelDeploymentPropertiesClass)
            if dp is None:
                return None
            return {"urn": urn, "status": str(dp.status) if dp.status else None,
                    "description": dp.description}
        return self._call("get_deployment", run, urn=urn)

    def get_training_inputs(self, dpi_urn: str) -> list[str]:
        """The input dataset URNs of a dataProcessInstance training run."""
        def run() -> list[str]:
            di = self._graph.get_aspect(dpi_urn, M.DataProcessInstanceInputClass)
            return list(di.inputs or []) if di else []
        return self._call("get_training_inputs", run, dpi_urn=dpi_urn)

    def get_ownership(self, urn: str) -> list[str]:
        """Owner URNs of an entity (empty if none)."""
        def run() -> list[str]:
            own = self._graph.get_ownership(urn)
            return [o.owner for o in own.owners] if own else []
        return self._call("get_ownership", run, urn=urn)

    def get_tags(self, urn: str) -> list[str]:
        """Tag URNs on an entity (empty if none)."""
        def run() -> list[str]:
            tags = self._graph.get_tags(urn)
            return [t.tag for t in tags.tags] if tags else []
        return self._call("get_tags", run, urn=urn)

    # -- writes (Phase 1D write-back) ------------------------------------- #
    #
    # These are the ONLY mutating calls in Blastradar. They are plumbing only —
    # the mutation policy gate (TOOLS_IS_MUTATION_ENABLED) and idempotency live in
    # writeback.py, which is the single caller. Each is idempotent by construction
    # (deterministic URN + upsert, or a full set-emit), so the retry in ``_call`` is
    # safe. All are verified live against GMS v1.5.0.6 (see docs/API-NOTES.md).

    def get_incident(self, incident_urn: str) -> dict | None:
        """Read an incident's IncidentInfo aspect, or None if it does not exist.

        Aspect read — immediately consistent (no index lag), so this is the
        idempotency check for :meth:`emit_incident` on a deterministic URN.
        """
        def run() -> dict | None:
            info = self._graph.get_aspect(incident_urn, M.IncidentInfoClass)
            if info is None:
                return None
            return {
                "urn": incident_urn,
                "type": str(info.type) if info.type else None,
                "title": info.title,
                "description": info.description,
                "entities": list(info.entities or []),
                "state": str(info.status.state) if info.status else None,
            }
        return self._call("get_incident", run, incident_urn=incident_urn)

    def emit_incident(
        self,
        incident_urn: str,
        *,
        entity_urns: list[str],
        title: str,
        description: str,
        incident_type: str = "DATA_SCHEMA",
        priority: int | None = None,
        actor: str = "urn:li:corpuser:blastradar",
    ) -> str:
        """Create/replace an incident on a DETERMINISTIC URN via a raw aspect emit.

        We do NOT use the GraphQL ``raiseIncident`` mutation: it mints a random UUID
        URN, which cannot be made idempotent, and this GMS image exposes no way to
        list an entity's incidents for a dedupe read (the ``MLModel.incidents`` field
        is undefined). Emitting ``IncidentInfoClass`` on our own deterministic URN is
        idempotent (re-emit replaces in place) and immediately readable back via
        :meth:`get_incident`. Verified to surface in the DataHub UI's Incidents tab.

        ``entity_urns`` must be valid incident destinations — datasets work; mlModel
        URNs are REJECTED by this GMS (``/entities/* not a valid destination``), so
        writeback anchors the incident on the changed dataset. Returns the URN.
        """
        def run() -> str:
            stamp = M.AuditStampClass(time=int(time.time() * 1000), actor=actor)
            info = M.IncidentInfoClass(
                type=incident_type,
                entities=list(entity_urns),
                status=M.IncidentStatusClass(
                    state=M.IncidentStateClass.ACTIVE, lastUpdated=stamp),
                created=stamp,
                title=title,
                description=description,
                priority=priority,
            )
            self._graph.emit_mcp(
                MetadataChangeProposalWrapper(entityUrn=incident_urn, aspect=info))
            return incident_urn
        return self._call("emit_incident", run, incident_urn=incident_urn,
                          entity_urns=entity_urns, title=title)

    def set_tags(self, urn: str, tag_urns: list[str]) -> list[str]:
        """Replace an entity's GlobalTags with ``tag_urns`` (writeback pre-computes the union).

        Merge/dedup is the caller's job so it can report which tags are new; this is
        the raw set-emit. Returns the tags written (order-preserved).
        """
        def run() -> list[str]:
            tags = [M.TagAssociationClass(tag=t) for t in tag_urns]
            self._graph.emit_mcp(MetadataChangeProposalWrapper(
                entityUrn=urn, aspect=M.GlobalTagsClass(tags=tags)))
            return list(tag_urns)
        return self._call("set_tags", run, urn=urn, tag_urns=tag_urns)

    def get_document(self, document_urn: str) -> dict | None:
        """Return ``{urn, title}`` if a knowledge-base document exists, else None."""
        def run() -> dict | None:
            info = self._graph.get_aspect(document_urn, M.DocumentInfoClass)
            if info is None:
                return None
            title = getattr(info, "title", None)
            return {"urn": document_urn, "title": title}
        return self._call("get_document", run, document_urn=document_urn)

    def upsert_document(
        self,
        *,
        doc_id: str,
        title: str,
        text: str,
        subtype: str | None = None,
        related_assets: list[str] | None = None,
        custom_properties: dict[str, str] | None = None,
    ) -> str:
        """Create/replace a native knowledge-base Document (deterministic id -> idempotent).

        Uses the new-SDK ``Document.create_document`` (the ``Document(urn=...)`` + fluent
        setters shown in older docs raises "DocumentInfo aspect must be set" — corrected
        live). ``doc_id`` becomes the URN, so re-running upserts in place. Returns the URN.
        """
        def run() -> str:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # ExperimentalWarning + upsert overwrite notice
                from datahub.sdk.document import Document
                doc = Document.create_document(
                    id=doc_id, title=title, text=text, subtype=subtype,
                    related_assets=list(related_assets) if related_assets else None,
                    custom_properties=dict(custom_properties) if custom_properties else None,
                )
                self._sdk.entities.upsert(doc)
            return str(doc.urn)
        return self._call("upsert_document", run, doc_id=doc_id, title=title)

    def get_upstream_transform(self, downstream_urn: str, upstream_urn: str) -> str | None:
        """Best-effort SQL/transform for the edge upstream->downstream, if DataHub has it.

        Reads the downstream dataset's UpstreamLineage and returns the matching
        upstream's ``transformOperation`` / query, else None. (The ecommerce datapack
        leaves these unpopulated — see API-NOTES.)
        """
        def run() -> str | None:
            ul = self._graph.get_aspect(downstream_urn, M.UpstreamLineageClass)
            if not ul:
                return None
            for up in ul.upstreams or []:
                if getattr(up, "dataset", None) == upstream_urn:
                    q = getattr(up, "query", None)
                    if q:
                        return str(q)
            for fg in ul.fineGrainedLineages or []:
                op = getattr(fg, "transformOperation", None)
                if op:
                    return str(op)
            return None
        return self._call("get_upstream_transform", run,
                          downstream_urn=downstream_urn, upstream_urn=upstream_urn)
