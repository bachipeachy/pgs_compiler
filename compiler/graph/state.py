"""
State — immutable compilation state passed between stages.

Each compilation stage is a pure function: State → State.
State carries the Graph, accumulated errors/warnings,
structure configuration, projections, materialized paths, and
compiler evidence trace events.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pgs_compiler.compiler.graph.graph import Graph
from pgs_compiler.compiler.graph.trace import TraceEvent
from pgs_compiler.compiler.atoms.errors import CompilerError


@dataclass(frozen=True)
class State:
    """
    Immutable compilation state.

    Passed between compilation stages. Each stage returns a NEW
    State — no mutation. This guarantees:
    - Determinism (same input → same output)
    - Traceability (each stage boundary is an observable state)
    - Rollback (previous states remain valid)

    Fields:
        stage: Name of the stage that produced this state
        graph: The semantic graph (sole semantic authority)
        structure_config: Active STRUCTURE artifact configuration
        errors: Accumulated compiler errors (hard failures)
        warnings: Accumulated compiler warnings (advisory)
        projections: Named projections populated by S6 PROJECT
        materialized_paths: File paths written by S7 MATERIALIZE
        stage_metadata: Stage-specific accumulated data
        trace_events: Immutable compiler evidence events (append-only)
    """

    stage: str                                  # Current stage name (e.g., "S1_EXTRACT")
    graph: Graph                             # Current semantic graph state
    structure_config: MappingProxyType          # Active STRUCTURE artifact
    errors: tuple[CompilerError, ...]           # Accumulated errors
    warnings: tuple[CompilerError, ...]         # Accumulated warnings
    projections: MappingProxyType               # Named projections (populated by S6 PROJECT)
    materialized_paths: tuple[str, ...]         # Paths written by S7 MATERIALIZE
    stage_metadata: MappingProxyType            # Stage-specific accumulated data
    trace_events: tuple[TraceEvent, ...]     # Compiler evidence events (append-only)
    _next_event_id: int = 0                     # Auto-incrementing event ID counter

    @staticmethod
    def initial(structure_config: dict[str, Any]) -> "State":
        """
        Create the initial State for a compilation run.

        Args:
            structure_config: The STRUCTURE artifact dict that drives this build

        Returns:
            Empty State ready for S1 EXTRACT
        """
        return State(
            stage="INITIAL",
            graph=Graph.empty(),
            structure_config=MappingProxyType(structure_config),
            errors=(),
            warnings=(),
            projections=MappingProxyType({}),
            materialized_paths=(),
            stage_metadata=MappingProxyType({}),
            trace_events=(),
            _next_event_id=0,
        )

    @property
    def has_errors(self) -> bool:
        """Check if any errors have been accumulated."""
        return len(self.errors) > 0

    def with_graph(self, graph: Graph) -> "State":
        """Return new state with updated graph."""
        return State(
            stage=self.stage,
            graph=graph,
            structure_config=self.structure_config,
            errors=self.errors,
            warnings=self.warnings,
            projections=self.projections,
            materialized_paths=self.materialized_paths,
            stage_metadata=self.stage_metadata,
            trace_events=self.trace_events,
            _next_event_id=self._next_event_id,
        )

    def with_stage(self, stage: str) -> "State":
        """Return new state with updated stage name."""
        return State(
            stage=stage,
            graph=self.graph,
            structure_config=self.structure_config,
            errors=self.errors,
            warnings=self.warnings,
            projections=self.projections,
            materialized_paths=self.materialized_paths,
            stage_metadata=self.stage_metadata,
            trace_events=self.trace_events,
            _next_event_id=self._next_event_id,
        )

    def with_errors(self, *new_errors: CompilerError) -> "State":
        """Return new state with additional errors appended."""
        return State(
            stage=self.stage,
            graph=self.graph,
            structure_config=self.structure_config,
            errors=self.errors + tuple(new_errors),
            warnings=self.warnings,
            projections=self.projections,
            materialized_paths=self.materialized_paths,
            stage_metadata=self.stage_metadata,
            trace_events=self.trace_events,
            _next_event_id=self._next_event_id,
        )

    def with_warnings(self, *new_warnings: CompilerError) -> "State":
        """Return new state with additional warnings appended."""
        return State(
            stage=self.stage,
            graph=self.graph,
            structure_config=self.structure_config,
            errors=self.errors,
            warnings=self.warnings + tuple(new_warnings),
            projections=self.projections,
            materialized_paths=self.materialized_paths,
            stage_metadata=self.stage_metadata,
            trace_events=self.trace_events,
            _next_event_id=self._next_event_id,
        )

    def with_projections(self, projections: dict[str, Any]) -> "State":
        """Return new state with named projections set.

        Args:
            projections: Mapping of projection name (e.g. "canonical") to Projection
        """
        return State(
            stage=self.stage,
            graph=self.graph,
            structure_config=self.structure_config,
            errors=self.errors,
            warnings=self.warnings,
            projections=MappingProxyType(projections),
            materialized_paths=self.materialized_paths,
            stage_metadata=self.stage_metadata,
            trace_events=self.trace_events,
            _next_event_id=self._next_event_id,
        )

    def get_projection(self, name: str) -> Any:
        """Get a named projection by type name, or None if not present."""
        return self.projections.get(name)

    def with_materialized_paths(self, paths: tuple[str, ...]) -> "State":
        """Return new state with materialized paths set."""
        return State(
            stage=self.stage,
            graph=self.graph,
            structure_config=self.structure_config,
            errors=self.errors,
            warnings=self.warnings,
            projections=self.projections,
            materialized_paths=paths,
            stage_metadata=self.stage_metadata,
            trace_events=self.trace_events,
            _next_event_id=self._next_event_id,
        )

    def with_metadata(self, key: str, value: Any) -> "State":
        """Return new state with an additional metadata entry."""
        updated = dict(self.stage_metadata)
        updated[key] = value
        return State(
            stage=self.stage,
            graph=self.graph,
            structure_config=self.structure_config,
            errors=self.errors,
            warnings=self.warnings,
            projections=self.projections,
            materialized_paths=self.materialized_paths,
            stage_metadata=MappingProxyType(updated),
            trace_events=self.trace_events,
            _next_event_id=self._next_event_id,
        )

    def with_trace_event(self, event: TraceEvent) -> "State":
        """Return new state with an additional trace event appended.

        Auto-assigns a sequential event_id to the event.
        """
        assigned = event.with_event_id(self._next_event_id)
        return State(
            stage=self.stage,
            graph=self.graph,
            structure_config=self.structure_config,
            errors=self.errors,
            warnings=self.warnings,
            projections=self.projections,
            materialized_paths=self.materialized_paths,
            stage_metadata=self.stage_metadata,
            trace_events=self.trace_events + (assigned,),
            _next_event_id=self._next_event_id + 1,
        )

    def with_trace_events(self, *events: TraceEvent) -> "State":
        """Return new state with multiple trace events appended.

        Auto-assigns sequential event_ids to all events.
        """
        next_id = self._next_event_id
        assigned: list[TraceEvent] = []
        for event in events:
            assigned.append(event.with_event_id(next_id))
            next_id += 1
        return State(
            stage=self.stage,
            graph=self.graph,
            structure_config=self.structure_config,
            errors=self.errors,
            warnings=self.warnings,
            projections=self.projections,
            materialized_paths=self.materialized_paths,
            stage_metadata=self.stage_metadata,
            trace_events=self.trace_events + tuple(assigned),
            _next_event_id=next_id,
        )
