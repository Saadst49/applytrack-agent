import unittest
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.memory import Memory
from app.model_client import ScriptedModel
from app.models import SearchApplicationsInput
from app.tools import AddApplicationInput


class ApiIntegrationTests(unittest.TestCase):
    def setUp(self):
        app.state.memory = Memory()
        app.state.busy = set()
        self.original_provider = settings.model_provider
        self.original_model_name = settings.model_name
        self.original_api_key = settings.gemini_api_key
        settings.model_provider = 'gemini'
        settings.model_name = 'scripted'
        settings.gemini_api_key = 'test-key'

    def tearDown(self):
        settings.model_provider = self.original_provider
        settings.model_name = self.original_model_name
        settings.gemini_api_key = self.original_api_key
        app.state.memory = Memory()
        app.state.busy = set()

    def test_health_and_models_are_real(self):
        with TestClient(app) as client:
            health = client.get('/health')
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.json()['implementation'], 'ApplyTrack Agent')

            models = client.get('/models')
            self.assertEqual(models.status_code, 200)
            self.assertEqual(models.json()['models'], ['scripted'])

    def test_chat_rejects_invalid_model(self):
        with TestClient(app) as client:
            response = client.post(
                '/chat',
                json={'session_id': 'session-invalid-model-123', 'task': 'Track a job', 'model': 'not-allowed'},
            )
            self.assertEqual(response.status_code, 400)

    def test_multi_turn_clarification_across_same_session(self):
        session_id = 'session-clarify-12345678'
        repo = app.state.memory.get_session_repository(session_id)
        repo.add(
            AddApplicationInput(
                company='Systems Limited',
                role='ML Intern',
                application_date=date(2026, 1, 10),
                status='saved',
            )
        )
        repo.add(
            AddApplicationInput(
                company='Systems Limited',
                role='Backend Intern',
                application_date=date(2026, 1, 10),
                status='saved',
            )
        )

        ml_application = repo.search(SearchApplicationsInput(company='Systems Limited', role='ML Intern')).applications[0]

        with TestClient(app) as client:
            with patch(
                'app.agent.create_model_client',
                side_effect=[
                    ScriptedModel([
                        {'status': 'continue', 'action': 'search_applications', 'arguments': {'company': 'Systems Limited'}},
                        {'status': 'needs_clarification', 'user_message': 'I found two matching applications. Which role do you mean?'}
                    ]),
                    ScriptedModel([
                        {'status': 'continue', 'action': 'search_applications', 'arguments': {'company': 'Systems Limited', 'role': 'ML Intern'}},
                        {'status': 'continue', 'action': 'update_application', 'arguments': {'application_id': ml_application.application_id, 'status': 'interview'}},
                        {'status': 'completed', 'user_message': 'Updated the ML Intern application to interview.'}
                    ]),
                ],
            ):
                first_turn = client.post(
                    '/chat',
                    json={'session_id': session_id, 'task': 'Update my Systems Limited application to interview.', 'model': 'scripted'},
                )
                self.assertEqual(first_turn.status_code, 200)
                self.assertEqual(first_turn.json()['status'], 'needs_clarification')
                self.assertIn('which role', first_turn.json()['final_response'].lower())

                second_turn = client.post(
                    '/chat',
                    json={'session_id': session_id, 'task': 'The ML Intern one.', 'model': 'scripted'},
                )
                self.assertEqual(second_turn.status_code, 200)
                self.assertEqual(second_turn.json()['status'], 'completed')
                self.assertIn('ML Intern', second_turn.json()['final_response'])
                self.assertGreaterEqual(len(client.app.state.memory.get(session_id)), 4)

    def test_missing_add_information_continues_same_session(self):
        session_id = 'session-add-clarify-12345678'

        with TestClient(app) as client:
            with patch(
                'app.agent.create_model_client',
                side_effect=[
                    ScriptedModel([
                        {'status': 'needs_clarification', 'user_message': 'I need the company and role for the new application.'}
                    ]),
                    ScriptedModel([
                        {'status': 'continue', 'action': 'add_application', 'arguments': {
                            'company': 'Arbisoft',
                            'role': 'AI Intern',
                            'application_date': date(2026, 2, 1),
                            'status': 'saved',
                        }},
                        {'status': 'completed', 'user_message': 'Tracked the Arbisoft AI Intern application.'}
                    ]),
                ],
            ):
                first_turn = client.post(
                    '/chat',
                    json={'session_id': session_id, 'task': 'Track my new job application.', 'model': 'scripted'},
                )
                self.assertEqual(first_turn.status_code, 200)
                self.assertEqual(first_turn.json()['status'], 'needs_clarification')

                second_turn = client.post(
                    '/chat',
                    json={'session_id': session_id, 'task': 'Arbisoft, AI Intern.', 'model': 'scripted'},
                )
                self.assertEqual(second_turn.status_code, 200)
                self.assertEqual(second_turn.json()['status'], 'completed')
                self.assertIn('Arbisoft', second_turn.json()['final_response'])
                self.assertGreaterEqual(len(client.app.state.memory.get(session_id)), 2)

    def test_chat_session_state_is_isolated_and_reset_clears_it(self):
        session_id = 'session-reset-12345678'
        repo = app.state.memory.get_session_repository(session_id)
        repo.add(
            AddApplicationInput(
                company='Nova Wave',
                role='Platform Engineer',
                application_date=date(2026, 3, 1),
                status='saved',
            )
        )
        app.state.memory.add(session_id, 'Track this record', 'Saved it.')

        another_session = 'session-other-12345678'
        another_repo = app.state.memory.get_session_repository(another_session)
        self.assertEqual(
            len(another_repo.search(SearchApplicationsInput(company='Nova Wave', role='Platform Engineer')).applications),
            0,
        )

        with TestClient(app) as client:
            delete_response = client.delete(f'/chat/{session_id}')
            self.assertEqual(delete_response.status_code, 200)
            self.assertEqual(client.app.state.memory.get(session_id), [])
            self.assertNotIn(session_id, client.app.state.memory.repositories)
            self.assertEqual(
                len(
                    client.app.state.memory
                    .get_session_repository(session_id)
                    .search(SearchApplicationsInput(company='Nova Wave', role='Platform Engineer'))
                    .applications
                ),
                0,
            )

    def test_arena_run_stays_isolated_from_chat_state(self):
        session_id = 'session-arena-isolation-12345678'
        repo = app.state.memory.get_session_repository(session_id)
        repo.add(
            AddApplicationInput(
                company='Acme Labs',
                role='AI Engineer',
                application_date=date(2026, 4, 1),
                status='saved',
            )
        )

        with TestClient(app) as client:
            with patch(
                'app.agent.create_model_client',
                return_value=ScriptedModel([
                    {'status': 'continue', 'action': 'search_applications', 'arguments': {'company': 'Acme Labs', 'role': 'AI Engineer'}},
                    {'status': 'completed', 'user_message': 'The search is complete.'},
                ]),
            ):
                response = client.post(
                    '/arena/run',
                    json={
                        'task': 'Search for my Acme Labs AI Engineer application.',
                        'arena_config': {'max_steps': 2, 'fault': 'none'},
                    },
                )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['status'], 'completed')
            self.assertEqual(response.json()['stop_reason'], 'model_completed')


if __name__ == '__main__':
    unittest.main()
