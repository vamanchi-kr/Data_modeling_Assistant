"""
Databricks Unity Catalog client — catalog/schema/table browsing with full metadata.

Performance design
------------------
All list operations that touch multiple schemas or tables use a
ThreadPoolExecutor so N round-trips fire concurrently instead of
sequentially.  Callers cache the results in Streamlit session state;
the client itself is stateless.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound, PermissionDenied, ResourceDoesNotExist

# Maximum concurrent HTTP calls to Unity Catalog REST API.
# Keep below 20 to avoid rate-limit 429s on large workspaces.
_MAX_WORKERS = 12


class DatabricksClient:
    """Thin wrapper around the Databricks SDK focused on Unity Catalog metadata."""

    def __init__(self, host: str, token: str) -> None:
        self._host = host.rstrip("/")
        self._token = token
        self._ws = WorkspaceClient(host=self._host, token=self._token)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def test_connection(self) -> str:
        """Return the current user's display name on success, raise on failure."""
        me = self._ws.current_user.me()
        return me.display_name or me.user_name or "unknown"

    # ------------------------------------------------------------------
    # Catalog browser — individual calls (used internally)
    # ------------------------------------------------------------------

    def list_catalogs(self) -> list[str]:
        """Return catalog names the token can see."""
        try:
            return sorted(c.name for c in self._ws.catalogs.list() if c.name)
        except PermissionDenied:
            return []

    def _list_schemas_raw(self, catalog: str) -> list[str]:
        try:
            return sorted(
                s.name
                for s in self._ws.schemas.list(catalog_name=catalog)
                if s.name
            )
        except (PermissionDenied, NotFound, ResourceDoesNotExist):
            return []

    def _list_tables_raw(self, catalog: str, schema: str) -> list[dict[str, str]]:
        try:
            results = []
            for t in self._ws.tables.list(catalog_name=catalog, schema_name=schema):
                results.append(
                    {
                        "name": t.name or "",
                        "full_name": t.full_name or f"{catalog}.{schema}.{t.name}",
                        "table_type": (
                            t.table_type.value if t.table_type else "UNKNOWN"
                        ),
                        "comment": t.comment or "",
                    }
                )
            return sorted(results, key=lambda x: x["name"])
        except (PermissionDenied, NotFound, ResourceDoesNotExist):
            return []

    # ------------------------------------------------------------------
    # Fast bulk fetchers — parallel across schemas / tables
    # ------------------------------------------------------------------

    def prefetch_catalog(
        self, catalog: str
    ) -> dict[str, list[dict[str, str]]]:
        """
        Fetch ALL schemas and their table lists for *catalog* in one
        parallel burst.

        Returns: {schema_name: [table_descriptor, ...]}

        On a catalog with 30 schemas this cuts wall-clock time from
        ~30 s (sequential) to ~3 s (parallel).
        """
        schemas = self._list_schemas_raw(catalog)
        if not schemas:
            return {}

        result: dict[str, list[dict[str, str]]] = {}

        def _fetch(schema: str) -> tuple[str, list[dict[str, str]]]:
            return schema, self._list_tables_raw(catalog, schema)

        with ThreadPoolExecutor(max_workers=min(len(schemas), _MAX_WORKERS)) as pool:
            for schema, tables in pool.map(_fetch, schemas):
                result[schema] = tables

        return result

    def prefetch_all_catalogs(
        self, catalogs: list[str]
    ) -> dict[str, dict[str, list[dict[str, str]]]]:
        """
        Prefetch every catalog in parallel (each catalog's schemas are
        themselves fetched in parallel inside prefetch_catalog).

        Returns: {catalog: {schema: [tables]}}
        """
        result: dict[str, dict] = {}

        def _fetch_cat(cat: str) -> tuple[str, dict]:
            return cat, self.prefetch_catalog(cat)

        with ThreadPoolExecutor(max_workers=min(len(catalogs), _MAX_WORKERS)) as pool:
            for cat, tree in pool.map(_fetch_cat, catalogs):
                result[cat] = tree

        return result

    # ------------------------------------------------------------------
    # Table detail — single and batch
    # ------------------------------------------------------------------

    def get_table_detail(self, full_name: str) -> dict[str, Any]:
        """
        Fetch full column-level metadata for a single table.

        Returns a dict shaped for consumption by the AI assistant:
        {
          name, full_name, table_type, comment, owner,
          columns: [{name, type, nullable, comment, is_partition}],
          properties: {k: v},
        }
        """
        try:
            t = self._ws.tables.get(full_name=full_name)
        except (NotFound, ResourceDoesNotExist) as exc:
            raise ValueError(f"Table not found: {full_name}") from exc

        columns = []
        for col in t.columns or []:
            columns.append(
                {
                    "name": col.name or "",
                    "type": col.type_text or (
                        col.type_name.value if col.type_name else "UNKNOWN"
                    ),
                    "nullable": col.nullable if col.nullable is not None else True,
                    "comment": col.comment or "",
                    "is_partition": col.partition_index is not None,
                    "mask_function": col.mask or None,
                }
            )

        return {
            "name": t.name or "",
            "full_name": t.full_name or full_name,
            "table_type": t.table_type.value if t.table_type else "UNKNOWN",
            "comment": t.comment or "",
            "owner": t.owner or "",
            "columns": columns,
            "properties": dict(t.properties or {}),
            "row_filter": None,
        }

    def get_multiple_table_details(
        self, full_names: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        Fetch column metadata for several tables in parallel.
        Tables that fail (permission / not-found) are silently skipped.

        Returns: {full_name: detail_dict}
        """
        result: dict[str, dict[str, Any]] = {}
        if not full_names:
            return result

        def _fetch(name: str) -> tuple[str, dict | None]:
            try:
                return name, self.get_table_detail(name)
            except Exception:
                return name, None

        with ThreadPoolExecutor(
            max_workers=min(len(full_names), _MAX_WORKERS)
        ) as pool:
            for name, detail in pool.map(_fetch, full_names):
                if detail is not None:
                    result[name] = detail

        return result

    # ------------------------------------------------------------------
    # Formatting helpers (used by the assistant to build context)
    # ------------------------------------------------------------------

    @staticmethod
    def format_schema_for_prompt(table_detail: dict[str, Any]) -> str:
        """
        Render a table's metadata as a compact, LLM-friendly text block.
        """
        lines: list[str] = []
        full = table_detail["full_name"]
        ttype = table_detail["table_type"]
        comment = table_detail["comment"]

        lines.append(f"TABLE: {full}  [{ttype}]")
        if comment:
            lines.append(f"  Description: {comment}")

        lines.append("  Columns:")
        for col in table_detail["columns"]:
            nullable = "" if col["nullable"] else " NOT NULL"
            partition = " [PARTITION]" if col["is_partition"] else ""
            col_comment = f"  -- {col['comment']}" if col["comment"] else ""
            lines.append(
                f"    {col['name']:40s} {col['type']:20s}{nullable}{partition}{col_comment}"
            )

        props = table_detail.get("properties", {})
        relevant_props = {
            k: v
            for k, v in props.items()
            if k.lower() in {"delta.minreaderversion", "delta.minwriterversion", "type", "format"}
        }
        if relevant_props:
            lines.append(f"  Properties: {relevant_props}")

        return "\n".join(lines)

    @staticmethod
    def format_multiple_schemas(tables: dict[str, dict[str, Any]]) -> str:
        """Format a collection of table details into a single context block."""
        if not tables:
            return "(no tables selected)"
        blocks = [
            DatabricksClient.format_schema_for_prompt(detail)
            for detail in tables.values()
        ]
        return "\n\n".join(blocks)
