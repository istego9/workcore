from __future__ import annotations

import json
import re
import time
import uuid
from copy import deepcopy
from typing import Any, Dict, List, Optional

from .evaluator import ExpressionContext, EvaluationError, ExpressionEvaluator
from .models import Edge, Event, Interrupt, Node, NodeRun, Run, Workflow


RUNNING = "RUNNING"
WAITING = "WAITING_FOR_INPUT"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

TO_DO = "TO_DO"
IN_PROGRESS = "IN_PROGRESS"
RESOLVED = "RESOLVED"
ERROR = "ERROR"

INT_OPEN = "OPEN"
INT_RESOLVED = "RESOLVED"
INT_CANCELLED = "CANCELLED"

_TEMPLATE_RE = re.compile(r"\{\{\s*(.+?)\s*\}\}")


class OrchestratorEngine:
    def __init__(
        self,
        workflow: Workflow,
        evaluator: ExpressionEvaluator,
        executors: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.workflow = workflow
        self.evaluator = evaluator
        self.executors = executors or {}
        self._incoming = self._build_incoming(workflow.edges)
        self._outgoing = self._build_outgoing(workflow.edges)

    def start_run(
        self,
        inputs: Dict[str, Any],
        mode: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Run:
        run = Run(
            id=self._new_id("run"),
            workflow_id=self.workflow.id,
            version_id=self.workflow.version_id,
            status=RUNNING,
            inputs=inputs,
            state={},
            mode=mode or "live",
            metadata=dict(metadata or {}),
        )
        return run

    def execute_until_blocked(self, run: Run) -> List[Event]:
        events: List[Event] = []
        if run.status == RUNNING and not run.node_runs:
            events.append(self._event("run_started", run))

        while run.status == RUNNING:
            runnable = self._runnable_nodes(run)
            if not runnable:
                break

            for node in runnable:
                events.extend(self._execute_node(run, node))
                if run.status != RUNNING:
                    break

        if run.status == COMPLETED:
            events.append(self._event("run_completed", run))
        if run.status == FAILED:
            events.append(self._event("run_failed", run))
        if run.status == WAITING:
            events.append(self._event("run_waiting_for_input", run))

        return events

    def resume_interrupt(
        self,
        run: Run,
        interrupt_id: str,
        input_data: Optional[Dict[str, Any]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Event]:
        interrupt = run.interrupts.get(interrupt_id)
        if not interrupt or interrupt.status != INT_OPEN:
            raise ValueError("Interrupt not found or not open")

        interrupt.status = INT_RESOLVED
        interrupt.input = input_data or {}
        interrupt.files = files or []

        if interrupt.input:
            run.state.setdefault("interrupts", {})[interrupt.id] = interrupt.input
            if interrupt.state_target:
                self._set_path(run.state, interrupt.state_target, interrupt.input)
            run.node_outputs[interrupt.node_id] = deepcopy(interrupt.input)

        node_run = run.node_runs.get(interrupt.node_id)
        if node_run:
            node_run.status = RESOLVED

        run.status = RUNNING
        return self.execute_until_blocked(run)

    def rerun_node(self, run: Run, node_id: str, scope: str) -> None:
        if node_id not in self.workflow.nodes:
            raise ValueError("Unknown node_id")

        reset_nodes = {node_id}
        if scope == "downstream":
            reset_nodes |= self._collect_downstream(node_id)
        elif scope != "node_only":
            raise ValueError("Invalid scope")

        for reset_id in reset_nodes:
            run.node_runs.pop(reset_id, None)
            run.node_outputs.pop(reset_id, None)

    def _execute_node(self, run: Run, node: Node) -> List[Event]:
        events: List[Event] = []
        emitted: List[Event] = []

        def emit(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
            emitted.append(self._event(event_type, run, node.id, payload))

        node_run = run.node_runs.get(node.id)
        if not node_run:
            node_run = NodeRun(node_id=node.id, status=TO_DO)
            run.node_runs[node.id] = node_run

        if node_run.status in (RESOLVED, ERROR):
            if node.type == "while":
                exit_target = node.config.get("exit_target")
                if run.branch_selection.get(node.id) != exit_target:
                    node_run.status = TO_DO
                else:
                    return events
            else:
                return events

        node_run.status = IN_PROGRESS
        events.append(self._event("node_started", run, node.id))

        try:
            started_at = time.monotonic()
            handler = getattr(self, f"_handle_{node.type}", None)
            if not handler:
                raise RuntimeError(f"Unknown node type: {node.type}")
            handler(run, node, emit)
            timeout_s = node.config.get("timeout_s")
            if timeout_s is not None:
                try:
                    timeout_value = float(timeout_s)
                except (TypeError, ValueError):
                    raise RuntimeError("timeout_s must be a number") from None
                elapsed = time.monotonic() - started_at
                if elapsed > timeout_value:
                    raise TimeoutError(f"Node {node.id} exceeded timeout ({elapsed:.2f}s)")
            events.extend(emitted)
            if run.status != WAITING:
                node_run.status = RESOLVED
                events.append(self._event("node_completed", run, node.id))
        except Exception as exc:
            max_retries = node.config.get("max_retries", 0) or 0
            try:
                max_retries = int(max_retries)
            except (TypeError, ValueError):
                max_retries = 0
            if node_run.attempt <= max_retries:
                node_run.last_error = str(exc)
                node_run.attempt += 1
                node_run.status = TO_DO
                node_run.output = None
                run.node_outputs.pop(node.id, None)
                run.status = RUNNING
                events.append(
                    self._event(
                        "node_retry",
                        run,
                        node.id,
                        {"attempt": node_run.attempt, "error": str(exc)},
                    )
                )
            else:
                node_run.status = ERROR
                node_run.last_error = str(exc)
                run.status = FAILED
                events.append(self._event("node_failed", run, node.id, {"error": str(exc)}))

        return events

    def _handle_start(self, run: Run, node: Node, emit) -> None:
        defaults = node.config.get("defaults", {})
        run.state = {**defaults, **run.inputs}
        run.node_outputs[node.id] = deepcopy(run.state)

    def _handle_if_else(self, run: Run, node: Node, emit) -> None:
        branches = node.config.get("branches", [])
        else_target = node.config.get("else_target")
        ctx = self._context(run)

        selected = None
        targets = []
        for branch in branches:
            condition = branch.get("condition")
            target = branch.get("target")
            if target:
                targets.append(target)
            if selected is None and condition is not None and target is not None:
                if self._eval_bool(condition, ctx):
                    selected = target
        if selected is None:
            selected = else_target

        if not selected:
            raise RuntimeError("If/Else node has no selected target")
        run.branch_selection[node.id] = selected

        other_targets = [t for t in targets if t != selected]
        if else_target and else_target != selected:
            other_targets.append(else_target)

        selected_reachable = self._reachable_from(selected)
        for target in other_targets:
            if target == selected:
                continue
            for skipped in self._reachable_from(target):
                if skipped not in selected_reachable:
                    run.skipped_nodes.add(skipped)

    def _handle_while(self, run: Run, node: Node, emit) -> None:
        condition = node.config.get("condition")
        max_iterations = node.config.get("max_iterations")
        body_target = node.config.get("body_target")
        exit_target = node.config.get("exit_target")
        loop_back = node.config.get("loop_back")

        if condition is None or max_iterations is None:
            raise RuntimeError("While node requires condition and max_iterations")
        if not body_target or not exit_target or not loop_back:
            raise RuntimeError("While node requires body_target, exit_target, and loop_back")

        iterations = run.loop_state.get(node.id, 0)
        if iterations >= max_iterations:
            raise RuntimeError("While node exceeded max_iterations")

        ctx = self._context(run)
        if self._eval_bool(condition, ctx):
            run.loop_state[node.id] = iterations + 1
            run.branch_selection[node.id] = body_target
            self._reset_loop_body(run, body_target, loop_back, exclude={node.id})
        else:
            run.branch_selection[node.id] = exit_target

    def _handle_set_state(self, run: Run, node: Node, emit) -> None:
        target = node.config.get("target")
        expression = node.config.get("expression")
        if not target or expression is None:
            raise RuntimeError("Set State requires target and expression")

        value = self._eval(expression, self._context(run))
        self._set_path(run.state, target, value)
        run.node_outputs[node.id] = deepcopy(value)

    def _handle_interaction(self, run: Run, node: Node, emit) -> None:
        prompt = node.config.get("prompt", "")
        if isinstance(prompt, str) and prompt:
            prompt = self._render_template(prompt, self._context(run))
        interrupt = Interrupt(
            id=self._new_id("intr"),
            run_id=run.id,
            node_id=node.id,
            type=node.config.get("type", "interaction"),
            status=INT_OPEN,
            prompt=prompt,
            input_schema=node.config.get("input_schema"),
            allow_file_upload=bool(node.config.get("allow_file_upload")),
            state_target=node.config.get("state_target"),
        )
        run.interrupts[interrupt.id] = interrupt
        run.status = WAITING

    def _handle_approval(self, run: Run, node: Node, emit) -> None:
        node.config.setdefault("type", "approval")
        self._handle_interaction(run, node, emit)

    def _handle_agent(self, run: Run, node: Node, emit) -> None:
        executor = self._resolve_agent_executor(run)
        context = self._context(run)
        resolved_config = dict(node.config or {})
        instructions = resolved_config.get("instructions")
        if isinstance(instructions, str) and instructions:
            resolved_config["instructions"] = self._render_template(instructions, context)
        user_input = resolved_config.get("user_input")
        if isinstance(user_input, str) and user_input:
            resolved_config["user_input"] = self._render_template(user_input, context)
        resolved_node = Node(node.id, node.type, resolved_config)
        result = executor(run, resolved_node, emit)
        run.node_outputs[node.id] = result.output
        self._merge_agent_output_into_state(run, resolved_node, result.output)
        node_run = run.node_runs.get(node.id)
        if node_run:
            node_run.output = result.output
            node_run.trace_id = result.trace_id
            node_run.usage = result.usage

    def _resolve_agent_executor(self, run: Run):
        preferred_mode = self._preferred_agent_mode(run)
        default_executor = self.executors.get("agent")
        live_executor = self.executors.get("agent_live")
        mock_executor = self.executors.get("agent_mock")
        explicit_mode = self._explicit_agent_mode_from_metadata(run)

        if preferred_mode == "live":
            if live_executor:
                return live_executor
            if explicit_mode != "live" and default_executor:
                return default_executor
            raise RuntimeError("Live agent executor not configured")
        if preferred_mode == "mock":
            if mock_executor:
                return mock_executor
            if default_executor:
                return default_executor
            raise RuntimeError("Mock agent executor not configured")

        if default_executor:
            return default_executor
        if live_executor:
            return live_executor
        raise RuntimeError("Agent executor not configured")

    def _preferred_agent_mode(self, run: Run) -> Optional[str]:
        explicit_mode = self._explicit_agent_mode_from_metadata(run)
        if explicit_mode is not None:
            return explicit_mode

        run_mode = (run.mode or "").strip().lower()
        if run_mode == "live":
            return "live"
        if run_mode == "test":
            return "mock"

        return None

    def _explicit_agent_mode_from_metadata(self, run: Run) -> Optional[str]:
        metadata = run.metadata or {}
        explicit_mode = metadata.get("agent_executor_mode")
        if isinstance(explicit_mode, str):
            normalized_mode = explicit_mode.strip().lower()
            if normalized_mode in {"live", "mock"}:
                return normalized_mode

        agent_mock = self._coerce_bool(metadata.get("agent_mock"))
        if agent_mock is not None:
            return "mock" if agent_mock else "live"

        llm_enabled = self._coerce_bool(metadata.get("llm_enabled"))
        if llm_enabled is not None:
            return "live" if llm_enabled else "mock"

        return None

    @staticmethod
    def _coerce_bool(value: Any) -> Optional[bool]:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if value == 1:
                return True
            if value == 0:
                return False
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return None

    def _handle_mcp(self, run: Run, node: Node, emit) -> None:
        executor = self.executors.get("mcp")
        if not executor:
            raise RuntimeError("MCP executor not configured")
        result = executor(run, node, emit)
        run.node_outputs[node.id] = result.output
        node_run = run.node_runs.get(node.id)
        if node_run:
            node_run.output = result.output

    def _merge_agent_output_into_state(self, run: Run, node: Node, output: Any) -> None:
        state_target = node.config.get("state_target")
        if isinstance(state_target, str) and state_target.strip():
            self._set_path(run.state, state_target.strip(), deepcopy(output))
            return

        if not self._should_auto_merge_agent_output(node):
            return
        if not isinstance(output, dict):
            return

        for key, value in output.items():
            if not isinstance(key, str) or not key:
                continue
            run.state[key] = deepcopy(value)

    @staticmethod
    def _should_auto_merge_agent_output(node: Node) -> bool:
        merge_output_raw = node.config.get("merge_output_to_state")
        if isinstance(merge_output_raw, bool):
            return merge_output_raw
        if isinstance(merge_output_raw, str):
            normalized = merge_output_raw.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False

        raw_format = node.config.get("output_format")
        if isinstance(raw_format, str):
            normalized = raw_format.strip().lower().replace("-", "_")
            if normalized in {"json", "json_schema", "jsonschema"}:
                return True
        if node.config.get("output_schema") is not None and not raw_format:
            return True
        return False

    def _handle_output(self, run: Run, node: Node, emit) -> None:
        expression = node.config.get("expression")
        if expression is None:
            run.outputs = node.config.get("value", {})
        else:
            run.outputs = {"result": self._eval(expression, self._context(run))}
        run.node_outputs[node.id] = deepcopy(run.outputs)

    def _handle_end(self, run: Run, node: Node, emit) -> None:
        run.status = COMPLETED

    def _runnable_nodes(self, run: Run) -> List[Node]:
        runnable: List[Node] = []
        for node_id, node in self.workflow.nodes.items():
            if node_id in run.skipped_nodes:
                continue
            node_run = run.node_runs.get(node_id)
            if node.type == "while" and node_run and node_run.status == RESOLVED:
                exit_target = node.config.get("exit_target")
                if run.branch_selection.get(node_id) == exit_target:
                    continue
            elif node_run and node_run.status in (IN_PROGRESS, RESOLVED, ERROR):
                continue
            if self._dependencies_resolved(run, node_id):
                runnable.append(node)
        return sorted(runnable, key=lambda n: n.id)

    def _dependencies_resolved(self, run: Run, node_id: str) -> bool:
        incoming = self._incoming.get(node_id, [])
        if not incoming:
            return True
        has_active = False
        node = self.workflow.nodes.get(node_id)
        loop_back = None
        loop_mode = None
        if node and node.type == "while":
            loop_back = node.config.get("loop_back")
            loop_mode = "reentry" if node_id in run.loop_state else "initial"
        for source in incoming:
            if loop_mode == "reentry" and loop_back and source != loop_back:
                continue
            if loop_mode == "initial" and loop_back and source == loop_back:
                continue
            if not self._is_edge_active(run, source, node_id):
                continue
            has_active = True
            source_run = run.node_runs.get(source)
            if not source_run or source_run.status != RESOLVED:
                return False
        return has_active

    def _is_edge_active(self, run: Run, source: str, target: str) -> bool:
        if source in run.skipped_nodes:
            return False
        source_node = self.workflow.nodes[source]
        if source_node.type in ("if_else", "while"):
            selected = run.branch_selection.get(source)
            return selected == target
        return True

    @staticmethod
    def _build_incoming(edges: List[Edge]) -> Dict[str, List[str]]:
        incoming: Dict[str, List[str]] = {}
        for edge in edges:
            incoming.setdefault(edge.target, []).append(edge.source)
        return incoming

    @staticmethod
    def _build_outgoing(edges: List[Edge]) -> Dict[str, List[str]]:
        outgoing: Dict[str, List[str]] = {}
        for edge in edges:
            outgoing.setdefault(edge.source, []).append(edge.target)
        return outgoing

    def _collect_downstream(self, node_id: str) -> set:
        visited = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            for target in self._outgoing.get(current, []):
                if target not in visited:
                    visited.add(target)
                    stack.append(target)
        return visited

    def _reachable_from(self, node_id: str) -> set:
        if node_id not in self.workflow.nodes:
            return set()
        visited = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            for target in self._outgoing.get(current, []):
                stack.append(target)
        return visited

    def _reverse_reachable_from(self, node_id: str) -> set:
        visited = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            for source in self._incoming.get(current, []):
                stack.append(source)
        return visited

    def _reset_loop_body(self, run: Run, body_target: str, loop_back: str, exclude: set) -> None:
        forward = self._reachable_from(body_target)
        backward = self._reverse_reachable_from(loop_back)
        loop_body = forward.intersection(backward)
        for node_id in loop_body:
            if node_id in exclude:
                continue
            run.node_runs.pop(node_id, None)
            run.node_outputs.pop(node_id, None)

    def _context(self, run: Run) -> ExpressionContext:
        return ExpressionContext(
            inputs=run.inputs,
            state=run.state,
            node_outputs=run.node_outputs,
        )

    def _render_template(self, template: str, context: ExpressionContext) -> str:
        def replace(match: re.Match[str]) -> str:
            expression = match.group(1).strip()
            value = self._eval(expression, context)
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False)
            return str(value)

        return _TEMPLATE_RE.sub(replace, template)

    def _eval(self, expression: str, context: ExpressionContext) -> Any:
        try:
            return self.evaluator.eval(expression, context)
        except EvaluationError as exc:
            raise RuntimeError(str(exc)) from exc

    def _eval_bool(self, expression: str, context: ExpressionContext) -> bool:
        result = self._eval(expression, context)
        return bool(result)

    def _event(
        self,
        event_type: str,
        run: Run,
        node_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Event:
        return Event(
            type=event_type,
            run_id=run.id,
            workflow_id=run.workflow_id,
            version_id=run.version_id,
            node_id=node_id,
            payload=payload,
            metadata=dict(run.metadata or {}),
        )

    @staticmethod
    def _new_id(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    @staticmethod
    def _set_path(state: Dict[str, Any], path: str, value: Any) -> None:
        parts = path.split(".")
        current = state
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        current[parts[-1]] = value
