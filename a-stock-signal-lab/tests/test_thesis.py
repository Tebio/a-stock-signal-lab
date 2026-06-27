import unittest

from fenjue.thesis import evaluate_logic_evidence


class ThesisEvidenceTests(unittest.TestCase):
    def test_media_story_alone_cannot_open_logic_gate(self):
        result = evaluate_logic_evidence([
            {"evidence_tier": "C", "exposure_direction": "positive",
             "exposure_confidence_ratio": 0.9, "event_type": "MEDIA_CATALYST"}
        ])
        self.assertFalse(result.eligible_for_new_entry)
        self.assertEqual(result.weakest_link, "NO_A_OR_B_LEVEL_POSITIVE_EVIDENCE")

    def test_hard_evidence_with_direct_exposure_can_open_candidate_gate(self):
        result = evaluate_logic_evidence([
            {"evidence_tier": "A", "exposure_direction": "positive",
             "exposure_confidence_ratio": 0.9, "event_type": "COMPANY_ANNOUNCEMENT"},
            {"evidence_tier": "B", "exposure_direction": "positive",
             "exposure_confidence_ratio": 0.8, "event_type": "PRODUCT_PRICE"},
        ])
        self.assertTrue(result.eligible_for_new_entry)
        self.assertGreaterEqual(result.exposure_purity_ratio, 0.8)

    def test_critical_a_level_negative_event_invalidates_logic(self):
        result = evaluate_logic_evidence([
            {"evidence_tier": "A", "exposure_direction": "negative",
             "exposure_confidence_ratio": 1.0, "event_type": "REGULATORY_INVESTIGATION",
             "severity": "critical"},
            {"evidence_tier": "A", "exposure_direction": "positive",
             "exposure_confidence_ratio": 1.0, "event_type": "COMPANY_ANNOUNCEMENT"},
        ])
        self.assertTrue(result.logic_invalidated)
        self.assertFalse(result.eligible_for_core_hold)


if __name__ == "__main__":
    unittest.main()
