import unittest

from apps.orchestrator.runtime.evaluator import CELPY_AVAILABLE, ExpressionContext

from apps.orchestrator.runtime import CelEvaluator


@unittest.skipIf(not CELPY_AVAILABLE, "cel-python not installed")
class CelEvaluatorTests(unittest.TestCase):
    def test_basic_math(self):
        evaluator = CelEvaluator()
        ctx = ExpressionContext(inputs={"x": 1}, state={}, node_outputs={})
        result = evaluator.eval("inputs.x + 1", ctx)
        self.assertEqual(result, 2)

    def test_boolean(self):
        evaluator = CelEvaluator()
        ctx = ExpressionContext(inputs={}, state={"flag": True}, node_outputs={})
        result = evaluator.eval("state.flag == true", ctx)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
