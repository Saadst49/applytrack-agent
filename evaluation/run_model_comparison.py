"""Run the real-model comparison experiment for ApplyTrack Agent.

Usage:
    python evaluation/run_model_comparison.py --models MODEL_A MODEL_B

The runner uses the configured Gemini adapter and the real bounded agent loop.
It writes JSON/CSV artifacts only after real runs complete. Missing provider
usage remains null, and costs remain null unless explicit pricing is supplied
with --pricing-json or APPLYTRACK_MODEL_PRICING_JSON.
"""
import argparse
import asyncio
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import run_agent
from app.config import settings
from app.model_client import ModelConfigurationError, create_model_client
from app.models import AddApplicationInput, ArenaRequest, SearchApplicationsInput
from app.tools import DATA_PATH, SandboxRepository


ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = Path(__file__).with_name('model_comparison_cases.json')
RESULTS_JSON = Path(__file__).with_name('model_comparison_results.json')
RESULTS_CSV = Path(__file__).with_name('model_comparison_results.csv')


def load_pricing(path):
    raw = Path(path).read_text(encoding='utf-8') if path else os.getenv('APPLYTRACK_MODEL_PRICING_JSON')
    if not raw:
        return {}
    value = json.loads(raw) if path else json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Pricing must be a JSON object keyed by model name.')
    return value


def build_repository(case):
    repository = SandboxRepository(DATA_PATH)
    for record in case.get('seed_records', []):
        repository.add(AddApplicationInput.model_validate(record))
    return repository


def find_application(repository, selector):
    matches = repository.search(SearchApplicationsInput(company=selector['company'], role=selector['role']))
    return matches.applications[0] if matches.applications else None


def request_for(case):
    return ArenaRequest(
        task=case['task'],
        external_context=case.get('external_context', []),
        arena_config={'max_steps': 6, 'fault': 'none'},
    )


def cost_for(model, usage, pricing):
    rates = pricing.get(model)
    if not isinstance(rates, dict) or not usage:
        return None
    input_rate = rates.get('input_usd_per_million_tokens')
    output_rate = rates.get('output_usd_per_million_tokens')
    if not isinstance(input_rate, (int, float)) or not isinstance(output_rate, (int, float)):
        return None
    if usage.get('input_tokens') is None or usage.get('output_tokens') is None:
        return None
    return (usage['input_tokens'] * input_rate + usage['output_tokens'] * output_rate) / 1_000_000


def action_sequence(result):
    return [trace.tool for trace in result.tool_calls if trace.attempt == 1]


def score_case(case, result, repository):
    sequence = action_sequence(result)
    expected_status = result.status in case['expected_statuses']
    expected_actions = sequence in case['acceptable_action_sequences']
    state_matches = True
    expected_application = case.get('expected_application')
    if expected_application:
        application = find_application(repository, expected_application)
        state_matches = application is not None and application.status == expected_application['status']

    unchanged = True
    selector = case.get('unchanged_application')
    if selector:
        application = find_application(repository, selector)
        unchanged = application is not None and application.status == selector['status']
    return {
        'task_success': bool(expected_status and expected_actions and state_matches and unchanged),
        'structured_output_first_pass_valid': not any(event.get('event') == 'contract_repair_attempt' for event in result.events),
        'structured_output_repair_needed': any(event.get('event') == 'contract_repair_attempt' for event in result.events),
        'structured_output_contract_failed': result.status == 'contract_error',
        'correct_action_selection': expected_actions,
        'observed_action_sequence': sequence,
        'expected_state_match': state_matches,
        'unchanged_external_content_state': unchanged,
    }


async def run_one(model_name, case, pricing):
    request = request_for(case)
    repository = build_repository(case)
    client = create_model_client(model_name, max_retries=0)
    started = perf_counter()
    try:
        result = await run_agent(request, [], model_name, model_client=client, repository=repository)
        provider_error = None
    except Exception as error:
        result = None
        provider_error = f'{type(error).__name__}: {error}'
    latency_ms = (perf_counter() - started) * 1000
    usage = getattr(client, 'total_usage', {})
    usage = {key: usage.get(key) for key in ('input_tokens', 'output_tokens', 'total_tokens')}
    if result is None:
        return {
            'model': model_name,
            'case': case['name'],
            'status': 'provider_error',
            'stop_reason': 'provider_error',
            'steps': 0,
            'latency_ms': latency_ms,
            'input_tokens': usage['input_tokens'],
            'output_tokens': usage['output_tokens'],
            'total_tokens': usage['total_tokens'],
            'approximate_cost_usd': cost_for(model_name, usage, pricing),
            'tool_sequence': [],
            'tool_calls': [],
            'events': [],
            'errors': [{'code': 'provider_error', 'message': provider_error}],
            'task_success': False,
            'structured_output_first_pass_valid': False,
            'structured_output_repair_needed': False,
            'structured_output_contract_failed': False,
            'correct_action_selection': False,
            'expected_state_match': False,
            'unchanged_external_content_state': True,
        }
    score = score_case(case, result, repository)
    return {
        'model': model_name,
        'case': case['name'],
        'status': result.status,
        'stop_reason': result.stop_reason,
        'steps': result.steps,
        'latency_ms': latency_ms,
        'input_tokens': usage['input_tokens'],
        'output_tokens': usage['output_tokens'],
        'total_tokens': usage['total_tokens'],
        'approximate_cost_usd': cost_for(model_name, usage, pricing),
        'tool_sequence': score['observed_action_sequence'],
        'tool_calls': [trace.model_dump() for trace in result.tool_calls],
        'events': result.events,
        'errors': result.errors,
        **{key: value for key, value in score.items() if key != 'observed_action_sequence'},
    }


def aggregate(rows):
    by_model = defaultdict(list)
    for row in rows:
        by_model[row['model']].append(row)
    summaries = []
    for model, model_rows in by_model.items():
        def rate(key):
            return sum(row[key] for row in model_rows) / len(model_rows)

        def average(key):
            values = [row[key] for row in model_rows if row[key] is not None]
            return sum(values) / len(values) if values else None

        summaries.append({
            'model': model,
            'cases': len(model_rows),
            'task_success_rate': rate('task_success'),
            'first_pass_structured_output_validity_rate': rate('structured_output_first_pass_valid'),
            'repair_rate': rate('structured_output_repair_needed'),
            'contract_failure_rate': rate('structured_output_contract_failed'),
            'correct_action_selection_rate': rate('correct_action_selection'),
            'average_latency_ms': average('latency_ms'),
            'average_input_tokens': average('input_tokens'),
            'average_output_tokens': average('output_tokens'),
            'average_total_tokens': average('total_tokens'),
            'average_approximate_cost_usd': average('approximate_cost_usd'),
        })
    return summaries


def write_artifacts(rows, summaries):
    RESULTS_JSON.write_text(json.dumps({'results': rows, 'summaries': summaries}, indent=2), encoding='utf-8')
    fields = [
        'model', 'case', 'status', 'stop_reason', 'steps', 'latency_ms',
        'input_tokens', 'output_tokens', 'total_tokens', 'approximate_cost_usd',
        'task_success', 'structured_output_first_pass_valid', 'structured_output_repair_needed',
        'structured_output_contract_failed', 'correct_action_selection',
        'expected_state_match', 'unchanged_external_content_state', 'tool_sequence', 'tool_calls', 'events', 'errors',
    ]
    with RESULTS_CSV.open('w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: json.dumps(row[field]) if isinstance(row[field], (list, dict)) else row[field] for field in fields})


async def run_experiment(models, pricing, existing_rows=None):
    cases = json.loads(CASES_PATH.read_text(encoding='utf-8'))
    rows = list(existing_rows or [])
    completed = {
        (row['model'], row['case'])
        for row in rows
        if row.get('status') != 'provider_error'
    }
    for model in models:
        for case in cases:
            if (model, case['name']) in completed:
                print(f'SKIP {model} / {case["name"]} (completed result)', flush=True)
                continue
            print(f'RUN {model} / {case["name"]}', flush=True)
            rows = [row for row in rows if (row['model'], row['case']) != (model, case['name'])]
            rows.append(await run_one(model, case, pricing))
            write_artifacts(rows, aggregate(rows))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', nargs='+', required=True, help='At least two distinct Gemini model identifiers.')
    parser.add_argument('--pricing-json', help='JSON file with per-model token rates; omitted costs remain null.')
    parser.add_argument('--resume', action='store_true', help='Reuse completed rows in existing result artifacts and retry provider-error rows.')
    args = parser.parse_args()
    models = list(dict.fromkeys(args.models))
    if len(models) < 2:
        parser.error('--models requires at least two distinct model names.')
    if not settings.gemini_api_key:
        raise SystemExit('Real model comparison requires GEMINI_API_KEY; no results files were generated.')
    settings.model_provider = 'gemini'
    try:
        pricing = load_pricing(args.pricing_json)
        existing_rows = []
        if args.resume and RESULTS_JSON.exists():
            existing = json.loads(RESULTS_JSON.read_text(encoding='utf-8'))
            existing_rows = existing.get('results', [])
        rows = asyncio.run(run_experiment(models, pricing, existing_rows=existing_rows))
    except ModelConfigurationError as error:
        raise SystemExit(f'Model configuration failed: {error}. No results files were generated.') from error
    summaries = aggregate(rows)
    write_artifacts(rows, summaries)
    print(json.dumps({'summaries': summaries, 'json': str(RESULTS_JSON), 'csv': str(RESULTS_CSV)}, indent=2))
    print('Recommendation deferred: choose a default only after reviewing measured reliability, action selection, latency, context, and token/cost results.')


if __name__ == '__main__':
    main()