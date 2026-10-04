import unittest
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from app.models import (
    AddApplicationInput,
    Fault,
    GenerateFollowupDraftInput,
    SearchApplicationsInput,
    UpdateApplicationInput,
)
from app.tools import SandboxRepository, ToolGateway


class ToolLayerTests(unittest.TestCase):
    def setUp(self):
        self.repository = SandboxRepository(
            Path(__file__).parents[1] / 'data' / 'sample_data.json'
        )
        self.gateway = ToolGateway(self.repository)

    def test_search_and_case_insensitive_search(self):
        result = self.gateway.dispatch('search_applications', {'company': 'NORTHSTAR'})
        self.assertTrue(result.success)
        self.assertEqual(result.output['total_matches'], 1)
        self.assertEqual(result.output['applications'][0]['application_id'], 'APP-001')

        result = self.gateway.dispatch('search_applications', {'role': 'engineering intern'})
        self.assertEqual(result.output['total_matches'], 1)

    def test_add_generates_id_and_rejects_duplicate(self):
        arguments = {
            'company': 'Cedar Labs',
            'role': 'Product Intern',
            'application_date': date(2026, 10, 1),
            'status': 'saved',
        }
        result = self.gateway.dispatch('add_application', arguments)
        self.assertTrue(result.success)
        self.assertEqual(result.output['application']['application_id'], 'APP-003')

        duplicate = self.gateway.dispatch('add_application', {**arguments, 'company': ' cedar labs '})
        self.assertFalse(duplicate.success)
        self.assertEqual(duplicate.error.code, 'duplicate_application')

    def test_update_success_missing_and_no_changes(self):
        result = self.gateway.dispatch(
            'update_application', {'application_id': 'APP-001', 'status': 'interview', 'notes': 'Next round.'}
        )
        self.assertTrue(result.success)
        self.assertEqual(result.output['application']['status'], 'interview')

        missing = self.gateway.dispatch('update_application', {'application_id': 'APP-999', 'status': 'saved'})
        self.assertFalse(missing.success)
        self.assertEqual(missing.error.code, 'missing_record')

        unchanged = self.gateway.dispatch('update_application', {'application_id': 'APP-001'})
        self.assertFalse(unchanged.success)
        self.assertEqual(unchanged.error.code, 'no_changes')

    def test_followup_draft_is_not_sent(self):
        result = self.gateway.dispatch(
            'generate_followup_draft',
            {'application_id': 'APP-001', 'purpose': 'ask for a status update'},
        )
        self.assertTrue(result.success)
        self.assertTrue(result.output['draft_only'])
        self.assertIn('status update', result.output['body'])

    def test_unknown_and_invalid_arguments_are_controlled(self):
        unknown = self.gateway.dispatch('delete_application', {})
        self.assertFalse(unknown.success)
        self.assertEqual(unknown.error.code, 'unknown_tool')

        invalid = self.gateway.dispatch('add_application', {'company': '', 'role': 'Engineer'})
        self.assertFalse(invalid.success)
        self.assertEqual(invalid.error.code, 'invalid_arguments')

    def test_typed_inputs_reject_unexpected_fields(self):
        with self.assertRaises(ValidationError):
            AddApplicationInput(
                company='Acme',
                role='Engineer',
                application_date=date(2026, 10, 1),
                status='saved',
                unexpected='nope',
            )
        SearchApplicationsInput(company='Acme')
        UpdateApplicationInput(application_id='APP-001', status='offer')

    def test_faults_are_one_shot_and_output_is_validated(self):
        timeout_gateway = ToolGateway(self.repository, Fault(type='tool_timeout'))
        timeout = timeout_gateway.dispatch('search_applications', {})
        self.assertFalse(timeout.success)
        self.assertEqual(timeout.error.code, 'tool_timeout')
        self.assertTrue(timeout_gateway.dispatch('search_applications', {}).success)

        malformed_gateway = ToolGateway(self.repository, Fault(type='malformed_tool_output'))
        malformed = malformed_gateway.dispatch('search_applications', {})
        self.assertFalse(malformed.success)
        self.assertEqual(malformed.error.code, 'malformed_tool_output')
        self.assertTrue(malformed_gateway.dispatch('search_applications', {}).success)


if __name__ == '__main__':
    unittest.main()