"""Bounded OBSERVE -> DECIDE -> VALIDATE -> ACT agent loop."""
from collections.abc import Sequence
from time import perf_counter
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import ValidationError

from app.config import settings
from app.model_client import ModelClient, ModelConfigurationError, create_model_client
from app.models import AgentDecision, AgentState, ArenaResponse, Fault, ToolTrace
from app.prompts import build_contract_repair_prompt, build_decision_messages
from app.tools import DATA_PATH, TOOLS, SandboxRepository, ToolGateway


async def run_agent(request, history: Sequence[BaseMessage], model: str, model_client: ModelClient | None = None,
                   repository: SandboxRepository | None = None):
    state = AgentState(goal=request.task)
    tool_calls: list[ToolTrace] = []
    errors: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    repository = repository or SandboxRepository(DATA_PATH)
    gateway = ToolGateway(repository, Fault(type=request.arena_config.fault.type))
    try:
        client = model_client or create_model_client(model)
    except ModelConfigurationError as error:
        return _response(request.request_id, state, 'failed', str(error), 'model_not_configured', tool_calls, errors, events)

    latest_observation: Any = None
    while state.step_count < request.arena_config.max_steps:
        messages = build_decision_messages(request.task, history, state, request.external_context, latest_observation)
        raw_decision = await client.decide(messages)
        state.step_count += 1
        state.model_calls += 1
        events.append({'step': state.step_count, 'event': 'decision_received'})

        if request.arena_config.fault.type == 'invalid_agent_decision' and not _fault_used(events):
            raw_decision = {'status': 'continue', 'action': 'not_a_registered_tool', 'arguments': {}}
            events.append({'step': state.step_count, 'event': 'invalid_decision_fault_injected'})

        decision = await _validate_decision(raw_decision, client, state, request.arena_config.max_steps, events, errors)
        if decision is None:
            return _response(request.request_id, state, 'contract_error', 'The model could not produce a valid decision.',
                             'decision_contract_invalid', tool_calls, errors, events)
        if decision.status == 'completed' and _requires_completion_evidence(decision.user_message, request.task) and latest_observation is None:
            errors.append({'code': 'premature_completion', 'message': 'Completed requires a validated tool observation.'})
            return _response(request.request_id, state, 'failed',
                             'The agent claimed completion without evidence of a completed operation.',
                             'completion_without_observation', tool_calls, errors, events)
        if decision.status != 'continue':
            return _terminal_response(request.request_id, state, decision, tool_calls, errors, events)

        state.last_action = decision.action
        events.append({'step': state.step_count, 'event': 'tool_selected', 'tool': decision.action})
        observation, traces = _execute_with_retries(
            gateway, decision.action, decision.arguments, state.step_count, request.arena_config.max_steps
        )
        tool_calls.extend(traces)
        latest_observation = observation
        state.last_observation = observation
        _update_known_state(state, observation)
        events.append({'step': state.step_count, 'event': 'tool_succeeded' if observation['success'] else 'tool_failed',
                       'tool': decision.action})
        if not observation['success']:
            error = observation['error']
            errors.append(error)
            if error['code'] in {'duplicate_application', 'missing_record', 'invalid_arguments', 'no_changes'}:
                events.append({'step': state.step_count, 'event': 'domain_error_observed', 'code': error['code']})
                continue
            return _response(request.request_id, state, 'tool_error', error['message'],
                             f"tool_{error['code']}", tool_calls, errors, events)

    return _response(request.request_id, state, 'budget_exceeded', 'The execution step budget was reached.',
                     'max_steps_reached', tool_calls, errors, events)


async def _validate_decision(raw: Any, client: ModelClient, state: AgentState, max_steps: int,
                             events: list[dict[str, Any]], errors: list[dict[str, Any]]) -> AgentDecision | None:
    candidate = raw
    repair_attempts = 0
    while True:
        try:
            decision = AgentDecision.model_validate(candidate)
            if decision.status == 'continue' and decision.action not in TOOLS:
                raise ValueError('Decision action is not registered.')
            events.append({'step': state.step_count, 'event': 'decision_validated'})
            return decision
        except (ValidationError, ValueError) as error:
            message = str(error)
            errors.append({'code': 'invalid_agent_decision', 'message': message})
            if repair_attempts >= settings.max_tool_retries or state.step_count >= max_steps:
                events.append({'step': state.step_count, 'event': 'contract_repair_exhausted'})
                return None
            repair_attempts += 1
            events.append({'step': state.step_count, 'event': 'contract_repair_attempt', 'attempt': repair_attempts})
            try:
                candidate = await client.decide([HumanMessage(content=build_contract_repair_prompt(message, candidate))])
            except Exception as repair_error:
                errors.append({'code': 'contract_repair_failed', 'message': str(repair_error)})
                events.append({'step': state.step_count, 'event': 'contract_repair_failed'})
                return None
            state.step_count += 1
            state.model_calls += 1


def _execute_with_retries(gateway: ToolGateway, tool_name: str, arguments: dict[str, Any], step: int, max_steps: int):
    traces: list[ToolTrace] = []
    max_attempts = min(settings.max_tool_retries + 1, max_steps)
    for attempt in range(1, max_attempts + 1):
        started = perf_counter()
        result = gateway.dispatch(tool_name, arguments)
        latency_ms = (perf_counter() - started) * 1000
        if result.success:
            traces.append(ToolTrace(step=step, tool=tool_name, attempt=attempt, outcome='success', latency_ms=latency_ms))
            return {'success': True, 'output': result.output}, traces
        code = result.error.code
        outcome = 'timeout' if code == 'tool_timeout' else 'malformed_output' if code == 'malformed_tool_output' else 'rejected'
        traces.append(ToolTrace(step=step, tool=tool_name, attempt=attempt, outcome=outcome, latency_ms=latency_ms))
        if code not in {'tool_timeout', 'malformed_tool_output'} or attempt >= max_attempts:
            return {'success': False, 'error': result.error.model_dump()}, traces
    return {'success': False, 'error': {'code': 'tool_failure', 'message': 'Tool retry budget exhausted.'}}, traces


def _update_known_state(state: AgentState, observation: dict[str, Any]) -> None:
    output = observation.get('output') or {}
    application = output.get('application')
    if application:
        state.target_application_id = application.get('application_id')
        state.known_company = application.get('company')
        state.known_role = application.get('role')
    if output.get('application_id'):
        state.target_application_id = output['application_id']


def _fault_used(events: list[dict[str, Any]]) -> bool:
    return any(event['event'] == 'invalid_decision_fault_injected' for event in events)


def _requires_completion_evidence(user_message: str | None, task: str) -> bool:
    text = f'{task} {user_message or ""}'.casefold()
    operation_terms = {
        'add', 'added', 'create', 'created', 'track', 'update', 'updated',
           'change', 'changed', 'search', 'searched', 'find', 'found', 'draft',
           'generate', 'generated', 'submitted', 'sent', 'tracked', 'completed',
    }
    return any(term in text for term in operation_terms)


def _terminal_response(request_id, state, decision, tool_calls, errors, events):
    messages = {
        'needs_clarification': decision.user_message or 'Please clarify the application you mean.',
        'completed': decision.user_message or 'The requested tracker operation is complete.',
        'blocked': decision.user_message or 'I cannot perform that external action.',
        'failed': decision.user_message or 'The agent could not complete the request.',
    }
    return _response(request_id, state, decision.status, messages[decision.status], f'model_{decision.status}',
                     tool_calls, errors, events)


def _response(request_id, state, status, final_response, stop_reason, tool_calls, errors, events):
    state.status = status
    state.stop_reason = stop_reason
    events.append({'step': state.step_count, 'event': 'agent_stop', 'reason': stop_reason})
    return ArenaResponse(request_id=request_id, status=status, final_response=final_response,
                         steps=state.step_count, stop_reason=stop_reason, tool_calls=tool_calls,
                         errors=errors, events=events,
                         metrics={'model_calls': state.model_calls})
