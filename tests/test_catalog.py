import copy
import json
import subprocess
import sys
import unittest
from datetime import datetime

from agente import catalog as demo


class ActiveCustomersTests(unittest.TestCase):
    def setUp(self):
        self.db = demo.connect()
        self.addCleanup(self.db.close)

    def test_three_distinct_contracts_share_ambiguous_synonym(self):
        self.assertEqual(len(demo.CONTRACTS), 3)
        for contract in demo.CONTRACTS.values():
            self.assertIn("clientes activos", contract["synonyms"])
            for field in ("owner", "version", "time", "freshness", "lineage"):
                self.assertIn(field, contract)

    def test_window_is_exactly_30_days_utc(self):
        for key in (demo.PRODUCT, demo.BUSINESS):
            time = demo.CONTRACTS[key]["time"]
            start = datetime.fromisoformat(time["start_inclusive"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(time["end_exclusive"].replace("Z", "+00:00"))
            self.assertEqual((end - start).total_seconds(), 30 * 86400)
            self.assertEqual(time["timezone"], "UTC")

    def test_expected_counts(self):
        actual = [demo.answer(self.db, metric_id=key)["value"] for key in demo.CONTRACTS]
        self.assertEqual(actual, [8, 5, 3])

    def test_all_23_golden_cases(self):
        results = demo.evaluate_goldens(self.db)
        self.assertEqual(len(results), 23)
        for result in results:
            with self.subTest(case=result["id"]):
                self.assertTrue(result["passed"], result["errors"])

    def test_ambiguous_question_does_not_pick_a_definition(self):
        result = demo.answer(self.db)
        self.assertEqual(result["status"], "needs_clarification")
        self.assertEqual(len(result["options"]), 3)
        self.assertNotIn("value", result)

    def test_unknown_metric_is_not_invented(self):
        result = demo.answer(self.db, metric_id="unknown.metric")
        self.assertEqual(result["status"], "unknown_metric")
        self.assertNotIn("value", result)

    def test_multiple_logins_count_customer_once(self):
        rows = self.db.execute("SELECT COUNT(*) FROM logins WHERE customer_id='c01'").fetchone()[0]
        self.assertEqual(rows, 2)
        self.assertEqual(demo.members(self.db, demo.PRODUCT).count("c01"), 1)

    def test_multiple_transactions_count_customer_once(self):
        rows = self.db.execute("SELECT COUNT(*) FROM transactions WHERE customer_id='c01'").fetchone()[0]
        self.assertEqual(rows, 2)
        self.assertEqual(demo.members(self.db, demo.BUSINESS).count("c01"), 1)

    def test_login_boundary_customers(self):
        self.assertEqual(demo.members(self.db, demo.PRODUCT),
                         ["c01", "c02", "c03", "c04", "c05", "c06", "c07", "c08"])

    def test_transaction_boundary_customers(self):
        ids = demo.members(self.db, demo.BUSINESS)
        self.assertIn("c04", ids)  # límite inferior exacto
        self.assertIn("c03", ids)  # un segundo antes del límite superior
        self.assertNotIn("c06", ids)  # límite superior exacto
        self.assertNotIn("c10", ids)  # un segundo antes del inferior

    def test_zero_reversed_and_pending_are_excluded(self):
        ids = demo.members(self.db, demo.BUSINESS)
        for customer in ("c07", "c08", "c09"):
            self.assertNotIn(customer, ids)

    def test_negative_posted_refund_counts(self):
        row = self.db.execute("SELECT amount_cents, status FROM transactions WHERE customer_id='c05'").fetchone()
        self.assertEqual(row, (-700, "posted"))
        self.assertIn("c05", demo.members(self.db, demo.BUSINESS))

    def test_finance_uses_correct_snapshot_and_positive_only(self):
        self.assertEqual(demo.members(self.db, demo.FINANCE), ["c01", "c06", "c10"])

    def test_finance_snapshot_is_complete_for_customer_universe(self):
        customers = set(self.db.execute("SELECT customer_id FROM customers"))
        snapshot = set(self.db.execute("SELECT customer_id FROM balances WHERE snapshot_date='2026-10-20'"))
        self.assertEqual(customers, snapshot)
        self.assertEqual(len(snapshot), 12)

    def test_canonical_answer_has_reproducible_provenance(self):
        result = demo.answer(self.db, metric_id=demo.BUSINESS)
        self.assertEqual(demo.validate_answer(result, {"status": "ok", "metric_id": demo.BUSINESS, "value": 5}), [])
        provenance = result["provenance"]
        replayed = [row[0] for row in self.db.execute(provenance["executed_sql"], provenance["parameters"])]
        self.assertEqual(replayed, ["c01", "c02", "c03", "c04", "c05"])
        self.assertEqual(replayed, provenance["customer_ids"])

    def test_freshness_is_fixed_not_a_claim_about_today(self):
        contract = copy.deepcopy(demo.CONTRACTS[demo.PRODUCT])
        self.assertEqual(demo.freshness(contract)["age_hours"], 2)
        self.assertTrue(demo.freshness(contract)["within_synthetic_sla"])
        contract["freshness"]["data_current_through_utc"] = "2026-10-19T00:00:00Z"
        self.assertFalse(demo.freshness(contract)["within_synthetic_sla"])

    def test_deliberately_wrong_count_is_rejected(self):
        result = demo.answer(self.db, metric_id=demo.BUSINESS)
        result["value"] = 8
        errors = demo.validate_answer(result, {"status": "ok", "metric_id": demo.BUSINESS, "value": 5})
        self.assertIn("value: expected=5, actual=8", errors)

    def test_missing_provenance_is_rejected(self):
        result = demo.answer(self.db, metric_id=demo.BUSINESS)
        del result["provenance"]
        self.assertTrue(demo.validate_answer(result, {"status": "ok", "value": 5}))

    def test_wrong_metric_or_dataset_version_is_rejected(self):
        for key in ("metric_version", "dataset_version"):
            with self.subTest(field=key):
                result = demo.answer(self.db, metric_id=demo.BUSINESS)
                result["provenance"][key] = "wrong-version"
                self.assertIn(f"provenance.{key} differs from canonical contract",
                              demo.validate_answer(result, {"status": "ok", "value": 5}))

    def test_altered_period_is_rejected(self):
        result = demo.answer(self.db, metric_id=demo.BUSINESS)
        result["provenance"]["time"]["start_inclusive"] = "2026-09-22T00:00:00Z"
        self.assertIn("provenance.time differs from canonical contract",
                      demo.validate_answer(result, {"status": "ok", "value": 5}))

    def test_altered_lineage_is_rejected(self):
        result = demo.answer(self.db, metric_id=demo.BUSINESS)
        result["provenance"]["lineage"]["table"] = "logins"
        self.assertIn("provenance.lineage differs from canonical contract",
                      demo.validate_answer(result, {"status": "ok", "value": 5}))

    def test_altered_freshness_is_rejected(self):
        result = demo.answer(self.db, metric_id=demo.BUSINESS)
        result["provenance"]["freshness"]["age_hours"] = 0
        self.assertIn("provenance.freshness differs from canonical contract",
                      demo.validate_answer(result, {"status": "ok", "value": 5}))

    def test_wrong_definition_unit_or_owner_is_rejected(self):
        for key in ("definition", "unit", "owner"):
            with self.subTest(field=key):
                result = demo.answer(self.db, metric_id=demo.BUSINESS)
                target = result["provenance"] if key == "owner" else result
                target[key] = "incorrect"
                field = "provenance.owner" if key == "owner" else key
                self.assertIn(f"{field} differs from canonical contract",
                              demo.validate_answer(result, {"status": "ok", "value": 5}))

    def test_wrong_evaluation_cutoff_is_rejected(self):
        result = demo.answer(self.db, metric_id=demo.BUSINESS)
        result["provenance"]["evaluation_as_of_utc"] = "2026-10-22T02:00:00Z"
        self.assertIn("provenance.evaluation_as_of_utc differs from canonical contract",
                      demo.validate_answer(result, {"status": "ok", "value": 5}))

    def test_noncanonical_sql_is_rejected(self):
        result = demo.answer(self.db, metric_id=demo.BUSINESS)
        result["provenance"]["executed_sql"] = "SELECT customer_id FROM customers"
        self.assertIn("provenance.executed_sql differs from canonical contract",
                      demo.validate_answer(result, {"status": "ok", "value": 5}))

    def test_wrong_query_parameters_are_rejected(self):
        result = demo.answer(self.db, metric_id=demo.BUSINESS)
        result["provenance"]["parameters"][0] = "2026-09-22T00:00:00Z"
        self.assertIn("provenance.parameters differs from canonical contract",
                      demo.validate_answer(result, {"status": "ok", "value": 5}))

    def test_editing_answer_does_not_mutate_the_contract(self):
        result = demo.answer(self.db, metric_id=demo.BUSINESS)
        result["provenance"]["time"]["days"] = 99
        result["provenance"]["lineage"]["table"] = "wrong"
        self.assertEqual(demo.CONTRACTS[demo.BUSINESS]["time"]["days"], 30)
        self.assertEqual(demo.CONTRACTS[demo.BUSINESS]["lineage"]["table"], "transactions")

    def test_cli_json_success(self):
        run = subprocess.run([sys.executable, "-m", "agente.catalog", "--json"],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertTrue(json.loads(run.stdout)["passed"])

    def test_cli_unknown_metric_exits_two(self):
        run = subprocess.run([sys.executable, "-m", "agente.catalog", "--metric-id", "unknown.metric"],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 2)
        self.assertEqual(json.loads(run.stdout)["status"], "unknown_metric")

    def test_lower_boundary_mutation_fails_with_expected_actual(self):
        run = subprocess.run([sys.executable, "-m", "agente.catalog", "--mutate-lower-bound"],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertIn("value: expected=8, actual=7", run.stdout)
        self.assertIn("value: expected=5, actual=4", run.stdout)
        self.assertIn("FAIL login_lower_included: expected=1, actual=0", run.stdout)
        self.assertIn("FAIL transaction_lower_included: expected=1, actual=0", run.stdout)


if __name__ == "__main__":
    unittest.main()
