# DataHub / SDK API Notes

Verified facts about the DataHub Python SDK that Blastradar depends on.

**Confirmation legend** — every signature below is tagged with how it was confirmed:

- `[introspect]` — read directly from the installed `acryl-datahub` package via
  `dir()`, `inspect.signature()`, and reading source under `site-packages`.
- `[docs]` — taken from the official docs.datahub.com tutorials/metamodel pages.
- `[run]` — confirmed by executing against a live DataHub instance.

> ⚠️ **Nothing here is `[run]`-confirmed yet.** During Phase 0 the local DataHub
> (`datahub docker quickstart`) was **not reachable** (Docker daemon down, GMS
> `:8080` unreachable) and no `.env` token was present. All signatures are
> `[introspect]` and/or `[docs]`. The items tagged **LIVE-VERIFY** below are
> behaviors (not signatures) that must be confirmed against the datapack before
> Phase 1 relies on them.

Environment used for introspection: Python **3.12.7** venv at `.venv/`,
`acryl-datahub` base install (no extras needed — the REST emitter, `DataHubGraph`,
and the new `datahub.sdk` client are all in the base package).

---

## Installed versions  `[introspect]`

| Package | Version | Notes |
| --- | --- | --- |
| `acryl-datahub` | **1.6.0.15** | `datahub.__version__`. Base install only. |
| Python | 3.12.7 | 3.11 not available on this machine; 3.13 avoided (SDK lag risk). |

Pinned in `pyproject.toml` as `acryl-datahub==1.6.0.15`.

The new high-level SDK lives under `datahub.sdk.*` and emits an
`ExperimentalWarning` on import ("import path will change from `from datahub.sdk
import ...` to `from datahub import ...` when promoted to stable"). We use it
anyway — it is the only surface exposing column-level lineage as a first-class
call (see below) — but pin the exact version because of the experimental status.

## Creating a DataHub client  `[introspect]` + `[docs]`

Two layers. Prefer the **new SDK client** for entities + lineage; drop to the
**graph client** for schema reads and GraphQL (incidents).

```python
from datahub.sdk import DataHubClient           # ExperimentalWarning on import

client = DataHubClient(server="http://localhost:8080", token=TOKEN)
# or, reading ~/.datahubenv / DATAHUB_GMS_URL + DATAHUB_GMS_TOKEN env:
client = DataHubClient.from_env()
client.test_connection()                          # -> None, raises on failure
```

`DataHubClient.__init__(*, server=None, token=None, graph=None, config=None)` `[introspect]`
`DataHubClient.from_env(*, client_mode=ClientMode.SDK, datahub_component=None)` `[introspect]`

Client sub-clients (all `@property`): `client.entities`, `client.lineage`,
`client.search`, `client.resolve`, `client.assertions`, `client.subscriptions`. `[introspect]`

The underlying graph is `client._graph` (private but stable) — used for schema
reads and `execute_graphql`. Or build one directly:

```python
from datahub.ingestion.graph.client import DataHubGraph, DatahubClientConfig
graph = DataHubGraph(DatahubClientConfig(server="http://localhost:8080", token=TOKEN))
# convenience: from datahub.ingestion.graph.client import get_default_graph
```

`DatahubClientConfig(*, server, token=None, timeout_sec=None, disable_ssl_verification=False, extra_headers=None, ...)` `[introspect]`

> **Never hardcode the token.** Read `DATAHUB_GMS_TOKEN` / `DATAHUB_GMS_URL` from
> `.env` (gitignored). `.from_env()` also reads `~/.datahubenv`.

## Reading entities and schema fields  `[introspect]`

New SDK (typed entity objects):

```python
entity = client.entities.get(urn)                 # -> Entity (typed subclass)
```
`EntityClient`: `get(urn)`, `create(entity, *, emit_mode=None)`,
`upsert(entity, *, emit_mode=None)`, `update(entity, *, emit_mode=None)`,
`delete(urn, check_exists=True, cascade=False, hard=False)`. `[introspect]`

Graph client (aspect-level reads — use for schema + lineage-raw):

```python
from datahub.metadata.schema_classes import SchemaMetadataClass
sm = graph.get_schema_metadata(dataset_urn)       # -> SchemaMetadataClass | None
for f in sm.fields:                               # List[SchemaFieldClass]
    f.fieldPath, f.nativeDataType, f.type, f.nullable
```
Other graph reads: `get_aspect(urn, aspect_type, version=0)`,
`get_aspects_for_entity(urn, aspects, aspect_types)`,
`get_entity_semityped(urn, aspects=None)`, `get_tags(urn)`,
`get_urns_by_filter(*, entity_types=None, platform=None, query=None, ...)` (search
for URNs — useful for the resolver when we only know platform + name). `[introspect]`

- `SchemaFieldClass(fieldPath, type: SchemaFieldDataTypeClass, nativeDataType, nullable, description, isPartOfKey, ...)` `[introspect]`
- `SchemaMetadataClass(schemaName, platform, version, hash, platformSchema, fields, primaryKeys, ...)` `[introspect]`

URN construction (`datahub.emitter.mce_builder` / `datahub.metadata.urns`):
```python
import datahub.emitter.mce_builder as b
b.make_dataset_urn(platform, name, env="PROD")
b.make_schema_field_urn(parent_urn, field_path)   # -> urn:li:schemaField:(<dataset_urn>,<field>)
```
`[introspect]` — verified output:
`urn:li:schemaField:(urn:li:dataset:(urn:li:dataPlatform:snowflake,db.schema.orders,PROD),order_total)`

> `client.resolve` only resolves **domain / term / user** — NOT datasets. To go
> from (platform, name, column) → URN, construct URNs with the builders above, or
> discover with `graph.get_urns_by_filter(...)`. (Matters for `resolver.py`.)

## Lineage queries (table-level and column-level)  `[introspect]` + `[docs]`

**This is the core of Blastradar and the SDK supports column granularity directly.**

```python
results = client.lineage.get_lineage(
    source_urn=dataset_urn,
    source_column="user_signup_date",   # omit for table-level lineage
    direction="downstream",             # or "upstream"
    max_hops=3,                          # multi-hop
    filter=None,                         # optional search Filter (FilterDsl)
    count=500,
)  # -> List[LineageResult]
```
`get_lineage(*, source_urn, source_column=None, direction='upstream', max_hops=1, filter=None, count=500) -> List[LineageResult]` `[introspect]`

Result shape `[introspect]`:
```python
LineageResult(urn, type, hops, direction, platform=None, name=None, description=None,
              paths: Optional[List[LineagePath]] = None)
LineagePath(urn, entity_name, column_name: Optional[str] = None)
```
So downstream column-level edges come back as `result.paths[i].column_name`. The
walker filters `result.urn` by entity type (`mlFeature`, `mlFeatureTable`,
`mlModel`, `mlModelDeployment`) to know when it has hit an ML asset.

Graph-level alternatives (lower level, if needed): `graph.scroll_lineage(*, urns,
relationship_types, direction, count, scroll_id, ...)`; `graph.parse_sql_lineage(sql,
*, platform, ...)`. `[introspect]`

Representation in the metadata model: column-level lineage is stored as
`fineGrainedLineages` inside the `upstreamLineage` aspect. `[docs]`
Column-level lineage **is available in DataHub Core / self-hosted** (not
Cloud-only) — satisfies architectural rule 2. `[docs]`

> **LIVE-VERIFY (Task 2):** the SDK *supports* column-level queries, but the
> **showcase-ecommerce datapack must actually contain column-level edges** for the
> premise to hold. `scripts/verify_cll.py` checks this. If absent, we emit a small
> column-level subgraph ourselves (changes the Phase 0 plan — flagged to the user).

## Creating ML entities (mlModelGroup, mlModel, mlFeatureTable, mlFeature)

**mlModelGroup / mlModel — new SDK classes** `[introspect]` + `[docs]`:

```python
from datahub.sdk.mlmodelgroup import MLModelGroup
from datahub.sdk.mlmodel import MLModel
from datahub.metadata.urns import MlModelGroupUrn

group = MLModelGroup(id="churn_model", platform="mlflow", name="Churn Model",
                     description="...", custom_properties={...})
client.entities.upsert(group)

model = MLModel(id="churn_model_v3", platform="mlflow", name="Churn Model v3",
                model_group=MlModelGroupUrn(platform="mlflow", name="churn_model"),
                training_metrics={"auc": "0.82"}, hyper_params={"depth": "6"},
                version="3")
model.add_deployment(deployment_urn)          # DeployedTo
model.add_training_job(dpi_urn)               # links dataProcessInstance training run
client.entities.upsert(model)
```
`MLModel(id, platform, version=None, ..., training_metrics=None, hyper_params=None, model_group=None, training_jobs=None, downstream_jobs=None, ...)` `[introspect]`
Mutators: `add_deployment`, `set_deployments`, `add_training_job`,
`add_training_metrics`, `add_hyper_params`, `set_model_group`, `add_version_alias`. `[introspect]`
`MLModelGroup(id, platform, name='', ..., description=None, custom_properties=None, training_jobs=None, ...)` `[introspect]`

> Docs use `client.entities.update(mlmodel)` in one place and `upsert` in another.
> `upsert` is the idempotent create-or-update we want for `seed_ml_graph.py`. `[docs]`

**mlFeatureTable / mlFeature — no new-SDK class; emit aspects via MCP** `[introspect]` + `[docs]`:

```python
import datahub.emitter.mce_builder as b
import datahub.metadata.schema_classes as models
from datahub.emitter.mcp import MetadataChangeProposalWrapper

feature_urn = b.make_ml_feature_urn(feature_table_name="customer_features",
                                    feature_name="days_since_signup")
ft_urn      = b.make_ml_feature_table_urn(platform="feast",
                                          feature_table_name="customer_features")

# FEATURE: sources create upstream lineage.
mcp_feature = MetadataChangeProposalWrapper(entityUrn=feature_urn,
    aspect=models.MLFeaturePropertiesClass(
        description="...",
        dataType="TIME",                       # MLFeatureDataTypeClass enum name
        sources=[schema_field_urn],            # see LIVE-VERIFY below
    ))

mcp_table = MetadataChangeProposalWrapper(entityUrn=ft_urn,
    aspect=models.MLFeatureTablePropertiesClass(
        description="...", mlFeatures=[feature_urn], mlPrimaryKeys=[...]))

graph.emit_mcp(mcp_feature); graph.emit_mcp(mcp_table)   # or graph.emit_mcps([...])
```
- `MLFeaturePropertiesClass(customProperties=None, description=None, dataType=None, version=None, sources=None)` `[introspect]`
- `MLFeatureTablePropertiesClass(customProperties=None, description=None, mlFeatures=None, mlPrimaryKeys=None)` `[introspect]`
- URN builders: `make_ml_feature_urn(feature_table_name, feature_name)`,
  `make_ml_feature_table_urn(platform, feature_table_name)`,
  `make_ml_model_urn(platform, model_name, env)`,
  `make_ml_model_group_urn(platform, group_name, env)`,
  `make_ml_model_deployment_urn(platform, deployment_name, env)`. `[introspect]`
- `MLFeatureDataTypeClass` enum names: `CONTINUOUS, ORDINAL, NOMINAL, COUNT, TIME,
  TEXT, BINARY, INTERVAL, ...` `[introspect]`

> **DISCREPANCY / KEY DESIGN POINT.** The docs example sets feature
> `sources=[dataset_urn]` — **dataset-level**. Blastradar needs **column-level**:
> a dropped *column* must reach the feature. `sources: List[str]` accepts any URN,
> so we will pass **schemaField URNs** (`make_schema_field_urn`). Trusting
> introspection over the docs example here.
> **LIVE-VERIFY:** confirm that a schemaField URN in `sources` produces a
> column-level lineage edge that `get_lineage(source_column=...)` traverses. If
> DataHub only honors dataset-level `sources`, fall back to emitting an explicit
> `fineGrainedLineage` on the feature's `upstreamLineage`.

**mlModelDeployment** `[introspect]`: emit `MLModelDeploymentPropertiesClass(
customProperties=None, externalUrl=None, description=None, createdAt=None,
version=None, status=None)` on a `make_ml_model_deployment_urn(...)` URN;
`status` uses `DeploymentStatusClass` (`IN_SERVICE, OUT_OF_SERVICE, CREATING, ...`).
Attach to a model with `model.add_deployment(deployment_urn)`.

## Creating training runs (dataProcessInstance)  `[introspect]` + `[docs]`

```python
from datahub.api.entities.dataprocess.dataprocess_instance import (
    DataProcessInstance, InstanceRunResult)
import datahub.metadata.schema_classes as models

dpi = DataProcessInstance(
    id="churn_model_v3-run",
    orchestrator="mlflow",
    template_urn=None,
    inlets=[DatasetUrn.from_string(training_dataset_urn)],   # input datasets
    subtype="MLFLOW_TRAINING_RUN",                            # required subtype
)
for mcp in dpi.generate_mcp(created_ts_millis=ts, materialize_iolets=True):
    graph.emit_mcp(mcp)
# hyperparams + metrics for the run:
graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=str(dpi.urn),
    aspect=models.MLTrainingRunPropertiesClass(
        id="churn_model_v3-run",
        hyperParams=[models.MLHyperParamClass(name="depth", value="6")],
        trainingMetrics=[models.MLMetricClass(name="auc", value="0.82")],
        outputUrls=[...])))
# link run -> model via model.add_training_job(str(dpi.urn))
```
- `DataProcessInstance(id, orchestrator, cluster=None, type='BATCH_SCHEDULED', template_urn=None, parent_instance=None, properties={}, url=None, inlets=[], outlets=[], upstream_urns=[], data_platform_instance=None, subtype=None, container_urn=None)` `[introspect]`
- Methods: `generate_mcp(created_ts_millis, materialize_iolets)`, `emit(emitter)`,
  `emit_process_start(...)`, `emit_process_end(..., result=InstanceRunResult.SUCCESS)`,
  `from_datajob`, `from_dataflow`, `from_container`. `[introspect]`
- `MLTrainingRunPropertiesClass(customProperties=None, externalUrl=None, id=None, outputUrls=None, hyperParams=[MLHyperParamClass], trainingMetrics=[MLMetricClass])` `[introspect]`
- `MLHyperParamClass(name, description=None, value=None, createdAt=None)`,
  `MLMetricClass(name, description=None, value=None, createdAt=None)` `[introspect]`
- Lineage created: Dataset → dataProcessInstance (training run) → mlModel
  (via `model.add_training_job`). Distinguishes **trained-on** columns (reachable
  through a training-run input dataset) from **inference-time** feature reads —
  the exact signal `scoring.py` needs. `[docs]`

> `Date.now()`-style timestamps: pass real epoch-millis at runtime (the scripts do
> `int(time.time()*1000)`); do not hardcode.

## Write operations (incident, tag, document)

**Incident — GraphQL `raiseIncident` (recommended, Core-supported)** `[docs]` + `[introspect]`:

```python
res = graph.execute_graphql("""
  mutation raiseIncident($input: RaiseIncidentInput!) {
    raiseIncident(input: $input)
  }""",
  variables={"input": {
      "type": "DATA_SCHEMA",          # IncidentType enum
      "title": "Upstream column dropped: orders.order_total",
      "description": "...blast radius...",
      "resourceUrn": impacted_urn,
  }})
```
`graph.execute_graphql(query, variables=None, operation_name=None, ...) -> Dict` `[introspect]`
Incidents are available in DataHub Core / self-hosted (not Cloud-only). `[docs]`

Lower-level alternative (aspect emit) — the SDK exposes `IncidentInfoClass(type,
entities: List[str], status: IncidentStatusClass, created: AuditStampClass, title,
description, priority, source, ...)`, `IncidentStatusClass(state, lastUpdated,
stage, message)`, `IncidentKeyClass(id)`; enums `IncidentTypeClass` = `DATA_SCHEMA,
FIELD, OPERATIONAL, FRESHNESS, VOLUME, SQL, CUSTOM`, `IncidentStateClass` =
`ACTIVE, RESOLVED`. There is **no** `graph.raise_incident` helper and **no**
`datahub.api.entities.incident` module. `[introspect]`
> **LIVE-VERIFY:** confirm `raiseIncident` is enabled on the quickstart image and
> returns an incident URN; if the mutation is unavailable, emit `IncidentInfoClass`
> on a `urn:li:incident:<uuid>` via `graph.emit_mcp`.

**Tag** `[introspect]`:
```python
import datahub.metadata.schema_classes as models
from datahub.emitter.mce_builder import make_tag_urn
graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=target_urn,
    aspect=models.GlobalTagsClass(tags=[
        models.TagAssociationClass(tag=make_tag_urn("blastradar:impacted"))])))
```
`GlobalTagsClass(tags: List[TagAssociationClass])`,
`TagAssociationClass(tag, context=None, attribution=None)`,
`make_tag_urn(tag)`. New-SDK entities also expose `.add_tag(...)`. Optionally
create the tag entity first via `datahub.sdk.tag.Tag(name=..., description=...,
color=...)`. `[introspect]`

**Document — new SDK `datahub.sdk.document.Document`** `[introspect]`:
```python
from datahub.sdk.document import Document
from datahub.metadata.urns import DocumentUrn
doc = (Document(urn=DocumentUrn("blastradar-<pr>-<sha>"))
       .set_title("Blast radius: orders.order_total dropped")
       .set_text(markdown_body)                 # the narrated report
       .add_related_asset(impacted_model_urn))
doc.set_subtype("blastradar-finding")
client.entities.upsert(doc)
```
`Document(urn: DocumentUrn)` with fluent `set_title`, `set_text`,
`set_source(source_type, external_url, external_id)`, `add_related_asset`,
`add_related_document`, `set_subtype`, `add_tag`, `set_custom_property`. `[introspect]`
> **LIVE-VERIFY:** confirm the `document` entity is registered in the quickstart
> GMS (it is a newer entity type). If not present on the image, fall back to
> `InstitutionalMemoryClass` links or the entity `description`/`DocumentationClass`
> aspect for the "saved document" write-back.

## MCP server tool names and arguments

> **NOT YET VERIFIED — separate component, not installed.**
>
> The DataHub **MCP server** (`mcp-server-datahub`, Acryl) is a *separate* package
> from `acryl-datahub` and is **not installed or connected** in this environment.
> Blastradar's deterministic core (rule 1) calls the **Python SDK directly**
> (`client.lineage.get_lineage`, `graph.emit_mcp`, etc.) — it does **not** require
> the MCP server on the critical path. The MCP server is optional (e.g. for an
> interactive/agent demo) and its tool names/arguments will only be filled in here
> if we decide to depend on it. **Decision pending with the user.**
