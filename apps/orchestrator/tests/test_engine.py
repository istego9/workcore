import unittest

from apps.orchestrator.runtime import (
    Edge,
    Node,
    OrchestratorEngine,
    SimpleEvaluator,
    Workflow,
)


class RuntimeEngineTests(unittest.TestCase):
    def _engine(self, nodes, edges, executors=None):
        workflow = Workflow(
            id="wf_1",
            version_id="v1",
            nodes={node.id: node for node in nodes},
            edges=edges,
        )
        return OrchestratorEngine(workflow, SimpleEvaluator(), executors)

    def test_linear_run(self):
        nodes = [
            Node("start", "start", {"defaults": {"count": 0}}),
            Node("set", "set_state", {"target": "count", "expression": "state['count'] + 1"}),
            Node("out", "output", {"expression": "state['count']"}),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "set"),
            Edge("set", "out"),
            Edge("out", "end"),
        ]
        engine = self._engine(nodes, edges)
        run = engine.start_run({})
        events = engine.execute_until_blocked(run)

        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.outputs, {"result": 1})
        self.assertTrue(any(evt.type == "run_completed" for evt in events))

    def test_agent_emits_message_event(self):
        nodes = [
            Node("start", "start"),
            Node("agent", "agent"),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "agent"),
            Edge("agent", "end"),
        ]

        def fake_agent_executor(run, node, emit):
            emit("message_generated", {"text": "hello"})
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(
                output={"ok": True},
                usage={"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
            )

        engine = self._engine(nodes, edges, executors={"agent": fake_agent_executor})
        run = engine.start_run({})
        events = engine.execute_until_blocked(run)

        self.assertTrue(any(evt.type == "message_generated" for evt in events))
        self.assertEqual(
            run.node_runs["agent"].usage,
            {"input_tokens": 12, "output_tokens": 8, "total_tokens": 20},
        )

    def test_agent_prompt_templates(self):
        nodes = [
            Node("start", "start"),
            Node("set", "set_state", {"target": "user", "expression": "inputs['user']"}),
            Node(
                "agent",
                "agent",
                {
                    "instructions": "Hello {{state['user']}} from {{inputs['source']}} prev={{node_outputs['set']}}",
                    "user_input": "order {{inputs['order_id']}}",
                },
            ),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "set"),
            Edge("set", "agent"),
            Edge("agent", "end"),
        ]

        def fake_agent_executor(run, node, emit):
            self.assertEqual(
                node.config.get("instructions"),
                "Hello Alice from webhook prev=Alice",
            )
            self.assertEqual(node.config.get("user_input"), "order 42")
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(output={"ok": True})

        engine = self._engine(nodes, edges, executors={"agent": fake_agent_executor})
        run = engine.start_run({"user": "Alice", "source": "webhook", "order_id": 42})
        engine.execute_until_blocked(run)
        self.assertEqual(run.node_outputs.get("set"), "Alice")

    def test_agent_prefers_live_executor_from_agent_mode_flag(self):
        nodes = [
            Node("start", "start"),
            Node("agent", "agent"),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "agent"),
            Edge("agent", "end"),
        ]
        calls = {"live": 0, "mock": 0}

        def live_agent_executor(run, node, emit):
            calls["live"] += 1
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(output={"mock": False})

        def mock_agent_executor(run, node, emit):
            calls["mock"] += 1
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(output={"mock": True})

        engine = self._engine(
            nodes,
            edges,
            executors={
                "agent": mock_agent_executor,
                "agent_live": live_agent_executor,
                "agent_mock": mock_agent_executor,
            },
        )
        run = engine.start_run({}, metadata={"agent_executor_mode": "live"})
        engine.execute_until_blocked(run)

        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.node_runs["agent"].output, {"mock": False})
        self.assertEqual(calls["live"], 1)
        self.assertEqual(calls["mock"], 0)

    def test_agent_prefers_mock_executor_when_llm_disabled(self):
        nodes = [
            Node("start", "start"),
            Node("agent", "agent"),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "agent"),
            Edge("agent", "end"),
        ]
        calls = {"live": 0, "mock": 0}

        def live_agent_executor(run, node, emit):
            calls["live"] += 1
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(output={"mock": False})

        def mock_agent_executor(run, node, emit):
            calls["mock"] += 1
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(output={"mock": True})

        engine = self._engine(
            nodes,
            edges,
            executors={
                "agent": live_agent_executor,
                "agent_live": live_agent_executor,
                "agent_mock": mock_agent_executor,
            },
        )
        run = engine.start_run({}, metadata={"llm_enabled": False})
        engine.execute_until_blocked(run)

        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.node_runs["agent"].output, {"mock": True})
        self.assertEqual(calls["live"], 0)
        self.assertEqual(calls["mock"], 1)

    def test_agent_live_mode_fails_when_live_executor_missing(self):
        nodes = [
            Node("start", "start"),
            Node("agent", "agent"),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "agent"),
            Edge("agent", "end"),
        ]

        def mock_agent_executor(run, node, emit):
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(output={"mock": True})

        engine = self._engine(
            nodes,
            edges,
            executors={
                "agent": mock_agent_executor,
                "agent_mock": mock_agent_executor,
            },
        )
        run = engine.start_run({}, metadata={"agent_executor_mode": "live"})
        engine.execute_until_blocked(run)

        self.assertEqual(run.status, "FAILED")
        self.assertIn("Live agent executor not configured", run.node_runs["agent"].last_error)

    def test_agent_prefers_live_executor_when_run_mode_live_without_metadata_flags(self):
        nodes = [
            Node("start", "start"),
            Node("agent", "agent"),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "agent"),
            Edge("agent", "end"),
        ]
        calls = {"live": 0, "mock": 0}

        def live_agent_executor(run, node, emit):
            calls["live"] += 1
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(output={"mock": False})

        def mock_agent_executor(run, node, emit):
            calls["mock"] += 1
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(output={"mock": True})

        engine = self._engine(
            nodes,
            edges,
            executors={
                "agent": mock_agent_executor,
                "agent_live": live_agent_executor,
                "agent_mock": mock_agent_executor,
            },
        )
        run = engine.start_run({}, mode="live")
        engine.execute_until_blocked(run)

        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.node_runs["agent"].output, {"mock": False})
        self.assertEqual(calls["live"], 1)
        self.assertEqual(calls["mock"], 0)

    def test_agent_structured_output_auto_merges_into_state(self):
        nodes = [
            Node("start", "start", {"defaults": {"submission_id": "sub_1"}}),
            Node(
                "classify_docs",
                "agent",
                {
                    "output_format": "json_schema",
                    "output_schema": {
                        "type": "object",
                        "required": ["document_classification"],
                        "properties": {
                            "document_classification": {"type": "array"},
                        },
                        "additionalProperties": False,
                    },
                },
            ),
            Node("output", "output", {"expression": "state"}),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "classify_docs"),
            Edge("classify_docs", "output"),
            Edge("output", "end"),
        ]

        def live_agent_executor(run, node, emit):
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(
                output={
                    "document_classification": [
                        {"doc_id": "doc_1", "doc_type": "other", "confidence": 0.9}
                    ]
                }
            )

        engine = self._engine(nodes, edges, executors={"agent": live_agent_executor})
        run = engine.start_run({})
        engine.execute_until_blocked(run)

        self.assertEqual(run.status, "COMPLETED")
        self.assertIn("document_classification", run.state)
        self.assertEqual(
            run.outputs,
            {
                "result": {
                    "submission_id": "sub_1",
                    "document_classification": [
                        {"doc_id": "doc_1", "doc_type": "other", "confidence": 0.9}
                    ],
                }
            },
        )

    def test_agent_merge_output_to_state_can_be_disabled(self):
        nodes = [
            Node("start", "start", {"defaults": {"submission_id": "sub_1"}}),
            Node(
                "extract_fields",
                "agent",
                {
                    "output_format": "json_schema",
                    "merge_output_to_state": False,
                    "output_schema": {
                        "type": "object",
                        "required": ["extracted_fields"],
                        "properties": {
                            "extracted_fields": {"type": "object"},
                        },
                        "additionalProperties": False,
                    },
                },
            ),
            Node("output", "output", {"expression": "state"}),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "extract_fields"),
            Edge("extract_fields", "output"),
            Edge("output", "end"),
        ]

        def live_agent_executor(run, node, emit):
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(output={"extracted_fields": {"insured": {"name": "ACME"}}})

        engine = self._engine(nodes, edges, executors={"agent": live_agent_executor})
        run = engine.start_run({})
        engine.execute_until_blocked(run)

        self.assertEqual(run.status, "COMPLETED")
        self.assertNotIn("extracted_fields", run.state)
        self.assertEqual(run.outputs, {"result": {"submission_id": "sub_1"}})

    def test_agent_output_can_be_written_to_explicit_state_target(self):
        nodes = [
            Node("start", "start"),
            Node(
                "extract_fields",
                "agent",
                {
                    "state_target": "contracts.extraction",
                },
            ),
            Node("output", "output", {"expression": "state"}),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "extract_fields"),
            Edge("extract_fields", "output"),
            Edge("output", "end"),
        ]

        def live_agent_executor(run, node, emit):
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(output={"extracted_fields": {"insured": {"name": "ACME"}}})

        engine = self._engine(nodes, edges, executors={"agent": live_agent_executor})
        run = engine.start_run({})
        engine.execute_until_blocked(run)

        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(
            run.state,
            {"contracts": {"extraction": {"extracted_fields": {"insured": {"name": "ACME"}}}}},
        )

    def test_if_else_branching(self):
        nodes = [
            Node("start", "start", {"defaults": {"flag": True}}),
            Node(
                "if1",
                "if_else",
                {
                    "branches": [
                        {"condition": "state['flag'] == True", "target": "a"},
                    ],
                    "else_target": "b",
                },
            ),
            Node("a", "set_state", {"target": "result", "expression": "'A'"}),
            Node("b", "set_state", {"target": "result", "expression": "'B'"}),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "if1"),
            Edge("if1", "a"),
            Edge("if1", "b"),
            Edge("a", "end"),
            Edge("b", "end"),
        ]
        engine = self._engine(nodes, edges)
        run = engine.start_run({})
        engine.execute_until_blocked(run)

        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.state.get("result"), "A")
        self.assertNotIn("b", run.node_outputs)

    def test_while_loop(self):
        nodes = [
            Node("start", "start", {"defaults": {"count": 0}}),
            Node(
                "loop",
                "while",
                {
                    "condition": "state['count'] < 3",
                    "max_iterations": 5,
                    "body_target": "inc",
                    "exit_target": "end",
                    "loop_back": "inc",
                },
            ),
            Node("inc", "set_state", {"target": "count", "expression": "state['count'] + 1"}),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "loop"),
            Edge("loop", "inc"),
            Edge("loop", "end"),
            Edge("inc", "loop"),
        ]
        engine = self._engine(nodes, edges)
        run = engine.start_run({})
        engine.execute_until_blocked(run)

        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.state.get("count"), 3)

    def test_interrupt_resume(self):
        nodes = [
            Node("start", "start"),
            Node(
                "ask",
                "interaction",
                {"prompt": "Approve?", "allow_file_upload": False, "state_target": "approved"},
            ),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "ask"),
            Edge("ask", "end"),
        ]
        engine = self._engine(nodes, edges)
        run = engine.start_run({})
        engine.execute_until_blocked(run)

        self.assertEqual(run.status, "WAITING_FOR_INPUT")
        interrupt_id = next(iter(run.interrupts))
        engine.resume_interrupt(run, interrupt_id, {"approved": True}, [])

        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.state.get("approved"), {"approved": True})

    def test_retry_then_success(self):
        nodes = [
            Node("start", "start"),
            Node("agent", "agent", {"max_retries": 1}),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "agent"),
            Edge("agent", "end"),
        ]
        attempts = {"count": 0}

        def flaky_agent(run, node, emit):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("boom")
            from apps.orchestrator.executors.types import ExecutorResult

            return ExecutorResult(output={"ok": True})

        engine = self._engine(nodes, edges, executors={"agent": flaky_agent})
        run = engine.start_run({})
        events = engine.execute_until_blocked(run)

        self.assertEqual(run.status, "COMPLETED")
        self.assertEqual(run.node_runs["agent"].attempt, 2)
        self.assertTrue(any(evt.type == "node_retry" for evt in events))

    def test_retry_exhausted_fails(self):
        nodes = [
            Node("start", "start"),
            Node("agent", "agent", {"max_retries": 0}),
            Node("end", "end"),
        ]
        edges = [
            Edge("start", "agent"),
            Edge("agent", "end"),
        ]

        def failing_agent(run, node, emit):
            raise RuntimeError("nope")

        engine = self._engine(nodes, edges, executors={"agent": failing_agent})
        run = engine.start_run({})
        events = engine.execute_until_blocked(run)

        self.assertEqual(run.status, "FAILED")
        self.assertTrue(any(evt.type == "node_failed" for evt in events))


if __name__ == "__main__":
    unittest.main()
