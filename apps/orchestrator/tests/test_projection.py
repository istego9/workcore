import unittest

from apps.orchestrator.runtime.projection import (
    apply_output_include_paths,
    apply_state_exclude_paths,
    normalize_projection_paths,
)


class ProjectionTests(unittest.TestCase):
    def test_normalize_projection_paths_validates_shape(self):
        normalized = normalize_projection_paths(
            ["documents.pages.image_base64", "result.claim_id", "result.claim_id"],
            field_name="state_exclude_paths",
        )
        self.assertEqual(normalized, ["documents.pages.image_base64", "result.claim_id"])

        with self.assertRaises(ValueError):
            normalize_projection_paths("documents", field_name="state_exclude_paths")
        with self.assertRaises(ValueError):
            normalize_projection_paths(["documents..bad"], field_name="state_exclude_paths")

    def test_apply_state_exclude_paths_removes_nested_document_payload(self):
        source = {
            "documents": [
                {
                    "doc_id": "doc_1",
                    "pages": [
                        {"page_number": 1, "image_base64": "AAAA", "artifact_ref": "artf_1"},
                        {"page_number": 2, "image_base64": "BBBB"},
                    ],
                }
            ]
        }
        projected = apply_state_exclude_paths(source, ["documents.pages.image_base64"])
        pages = projected["documents"][0]["pages"]
        self.assertNotIn("image_base64", pages[0])
        self.assertEqual(pages[0].get("artifact_ref"), "artf_1")
        self.assertNotIn("image_base64", pages[1])

    def test_apply_output_include_paths_keeps_only_selected_fields(self):
        outputs = {
            "result": {
                "claim_id": "clm_1",
                "decision": "approve",
                "totals": {"amount": 120, "currency": "USD"},
            }
        }
        projected = apply_output_include_paths(
            outputs,
            ["result.claim_id", "result.totals.amount"],
        )
        self.assertEqual(
            projected,
            {"result": {"claim_id": "clm_1", "totals": {"amount": 120}}},
        )


if __name__ == "__main__":
    unittest.main()

