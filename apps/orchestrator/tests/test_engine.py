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

            return ExecutorResult(output={"ok": True})

        engine = self._engine(nodes, edges, executors={"agent": fake_agent_executor})
        run = engine.start_run({})
        events = engine.execute_until_blocked(run)

        self.assertTrue(any(evt.type == "message_generated" for evt in events))

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
