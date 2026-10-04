"""Run deterministic public Reliability Arena cases.

The default local mode uses the bounded agent and sandbox tools with scripted
model decisions, so it does not require a paid provider. Use --http to exercise
the public /arena/run endpoint against a running server; that mode uses the
server's configured model and is provider-dependent.
"""
import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import run_agent
from app.model_client import ScriptedModel
from app.models import AddApplicationInput, ArenaRequest, SearchApplicationsInput
from app.tools import DATA_PATH, SandboxRepository


CASES_PATH = Path(__file__).with_name('public_cases.json')


def _repository(case):
    repository = SandboxRepository(DATA_PATH)
    for raw_record in case.get('seed_records', []):
        repository.add(AddApplicationInput.model_validate(raw_record))
    return repository


def _records(repository):
    return {
        application.application_id: application.model_dump(mode='json')
        for application in repository.search(SearchApplicationsInput()).applications
    }


async def _run_local(case):
    request = ArenaRequest.model_validate(case['request'])
    repository = _repository(case)
    before = _records(repository)
    model = ScriptedModel(case.get('scripted_responses', []))
    result = await run_agent(request, [], 'scripted', model_client=model, repository=repository)
    return result, before, repository


def _assert_result(case, result, before, repository):
    failures = []
    if result.status != case['expected_status']:
        failures.append(f"status={result.status!r}")
    if result.stop_reason != case['expected_stop_reason']:
        failures.append(f"stop_reason={result.stop_reason!r}")
    configured_steps = case['request']['arena_config']['max_steps']
    if result.steps > configured_steps:
        failures.append(f"steps={result.steps} exceeds {configured_steps}")

    expected_tools = case.get('expected_tool_sequence')
    if expected_tools is not None and [trace.tool for trace in result.tool_calls] != expected_tools:
        failures.append(f"tools={[trace.tool for trace in result.tool_calls]!r}")
    expected_outcomes = case.get('expected_tool_outcomes')
    if expected_outcomes is not None and [trace.outcome for trace in result.tool_calls] != expected_outcomes:
        failures.append(f"tool_outcomes={[trace.outcome for trace in result.tool_calls]!r}")
    actual_events = {event.get('event') for event in result.events}
    missing_events = [event for event in case.get('expected_event_names', []) if event not in actual_events]
    if missing_events:
        failures.append(f"missing_events={missing_events!r}")

    expected_status = case.get('expected_unchanged_status')
    if expected_status is not None:
        after = _records(repository)
        for application_id, record in before.items():
            if record['company'] == 'Northstar Analytics' and after[application_id]['status'] != expected_status:
                failures.append(f"record {application_id} was mutated")
    return failures


def run_local(cases):
    results = []
    for case in cases:
        try:
            result, before, repository = asyncio.run(_run_local(case))
            failures = _assert_result(case, result, before, repository)
            results.append((case, not failures, failures))
        except Exception as error:
            results.append((case, False, [f'{type(error).__name__}: {error}']))
    return results


def run_http(cases, url):
    results = []
    for case in cases:
        try:
            response = httpx.post(url.rstrip('/') + '/arena/run', json=case['request'], timeout=70)
            response.raise_for_status()
            result = response.json()
            failures = []
            if result.get('status') != case['expected_status']:
                failures.append(f"status={result.get('status')!r}")
            if result.get('stop_reason') != case['expected_stop_reason']:
                failures.append(f"stop_reason={result.get('stop_reason')!r}")
            if result.get('steps', 0) > case['request']['arena_config']['max_steps']:
                failures.append(f"steps={result.get('steps')} exceeds configured limit")
            results.append((case, not failures, failures))
        except (httpx.HTTPError, KeyError, ValueError) as error:
            results.append((case, False, [f'{type(error).__name__}: {error}']))
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--http', action='store_true', help='Use a running /arena/run server instead of local scripted mode.')
    parser.add_argument('--url', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    cases = json.loads(CASES_PATH.read_text(encoding='utf-8'))
    results = run_http(cases, args.url) if args.http else run_local(cases)

    categories = Counter(case['category'] for case, _, _ in results)
    category_passes = Counter(case['category'] for case, passed, _ in results if passed)
    for case, passed, failures in results:
        suffix = '' if passed else ' ' + '; '.join(failures)
        print(('PASS' if passed else 'FAIL') + f" [{case['category']}] {case['name']}{suffix}")
    for category in categories:
        print(f"{category}: {category_passes[category]}/{categories[category]} passed")
    passed = sum(1 for _, is_passed, _ in results if is_passed)
    print(f'{passed}/{len(results)} public Arena cases passed.')
    raise SystemExit(0 if passed == len(results) else 1)


if __name__ == '__main__':
    main()
