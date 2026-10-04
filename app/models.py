"""Domain-independent HTTP contracts. Add your own decision/state models below."""
from datetime import date
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid')
class ExternalContext(Contract):
    source: str = Field(min_length=1, max_length=100)
    content: str = Field(max_length=10000)
    trust: Literal['untrusted'] = 'untrusted'
class Fault(Contract):
    type: Literal['none', 'tool_timeout', 'malformed_tool_output', 'invalid_agent_decision'] = 'none'
    trigger: Literal['first_matching_operation'] = 'first_matching_operation'
class ArenaConfig(Contract):
    max_steps: int = Field(default=6, ge=1, le=6)
    fault: Fault = Field(default_factory=Fault)
    @field_validator('fault', mode='before')
    @classmethod
    def accept_assignment_shorthand(cls, value):
        return {'type': value} if isinstance(value, str) else value
class ArenaRequest(Contract):
    arena_version: Literal['0.1'] = '0.1'
    request_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=80)
    task: str = Field(min_length=1, max_length=10000)
    external_context: list[ExternalContext] = Field(default_factory=list, max_length=20)
    arena_config: ArenaConfig = Field(default_factory=ArenaConfig)
    @field_validator('task')
    @classmethod
    def nonblank(cls, value):
        if not value.strip(): raise ValueError('Task must not be blank')
        return value
class ToolTrace(Contract):
    step: int = Field(ge=1, le=6)
    tool: str
    attempt: int = Field(default=1, ge=1, le=3)
    outcome: Literal['success', 'timeout', 'malformed_output', 'rejected', 'exception']
    latency_ms: float = Field(default=0, ge=0)
class Metrics(Contract):
    latency_ms: float = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0, le=6)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)
class ArenaResponse(Contract):
    arena_version: Literal['0.1'] = '0.1'
    request_id: str
    status: Literal['completed', 'needs_clarification', 'blocked', 'approval_required', 'tool_error', 'contract_error', 'budget_exceeded', 'failed']
    final_response: str = Field(min_length=1, max_length=2000)
    steps: int = Field(default=0, ge=0, le=6)
    stop_reason: str
    tool_calls: list[ToolTrace] = Field(default_factory=list)
    errors: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    metrics: Metrics = Field(default_factory=Metrics)
class ChatRequest(ArenaRequest):
    session_id: str = Field(min_length=16, max_length=80)
    model: str = Field(default='unconfigured', max_length=120)


ApplicationStatus = Literal[
    'saved',
    'applied',
    'assessment',
    'interview',
    'offer',
    'rejected',
    'withdrawn',
]


class JobApplication(Contract):
    application_id: str = Field(min_length=1, max_length=100)
    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    application_date: date
    status: ApplicationStatus
    job_url: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=200)
    deadline: date | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator('application_id', 'company', 'role')
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError('Value must not be blank')
        return value

    @field_validator('job_url', 'location', 'notes', mode='before')
    @classmethod
    def normalize_empty_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


DecisionStatus = Literal[
    'continue',
    'needs_clarification',
    'completed',
    'blocked',
    'failed',
]

DecisionAction = Literal[
    'search_applications',
    'add_application',
    'update_application',
    'generate_followup_draft',
]


class AgentDecision(Contract):
    status: DecisionStatus
    action: DecisionAction | None = None
    arguments: dict = Field(default_factory=dict)
    user_message: str | None = Field(default=None, max_length=2000)

    @field_validator('user_message', mode='before')
    @classmethod
    def normalize_decision_message(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode='after')
    def validate_decision_shape(self):
        non_executable_statuses = {'needs_clarification', 'completed', 'blocked', 'failed'}
        if self.status == 'continue' and self.action is None:
            raise ValueError('continue decisions require an action')
        if self.status in non_executable_statuses and self.action is not None:
            raise ValueError('non-continue decisions must not contain an action')
        if self.status in {'needs_clarification', 'blocked'} and not self.user_message:
            raise ValueError(f'{self.status} decisions require a user_message')
        return self


class AgentState(Contract):
    goal: str = Field(min_length=1, max_length=10000)
    step_count: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    known_company: str | None = Field(default=None, max_length=200)
    known_role: str | None = Field(default=None, max_length=200)
    target_application_id: str | None = Field(default=None, max_length=100)
    last_action: DecisionAction | None = None
    last_observation: dict | None = None
    status: str = Field(default='running', min_length=1, max_length=50)
    stop_reason: str | None = Field(default=None, max_length=200)


class SearchApplicationsInput(Contract):
    application_id: str | None = Field(default=None, max_length=100)
    company: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200)


class SearchApplicationsOutput(Contract):
    applications: list[JobApplication] = Field(default_factory=list)
    total_matches: int = Field(ge=0)


class AddApplicationInput(Contract):
    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    application_date: date
    status: ApplicationStatus
    job_url: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=200)
    deadline: date | None = None
    notes: str | None = Field(default=None, max_length=5000)

    _normalize_required_text = field_validator('company', 'role')(JobApplication.required_text_must_not_be_blank)
    _normalize_optional_text = field_validator('job_url', 'location', 'notes', mode='before')(
        JobApplication.normalize_empty_optional_text
    )


class AddApplicationOutput(Contract):
    application: JobApplication


class UpdateApplicationInput(Contract):
    application_id: str = Field(min_length=1, max_length=100)
    company: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=200)
    application_date: date | None = None
    status: ApplicationStatus | None = None
    job_url: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=200)
    deadline: date | None = None
    notes: str | None = Field(default=None, max_length=5000)

    @field_validator('application_id', 'company', 'role')
    @classmethod
    def normalize_update_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError('Value must not be blank')
        return value

    _normalize_optional_text = field_validator('job_url', 'location', 'notes', mode='before')(
        JobApplication.normalize_empty_optional_text
    )


class UpdateApplicationOutput(Contract):
    application: JobApplication


class GenerateFollowupDraftInput(Contract):
    application_id: str = Field(min_length=1, max_length=100)
    purpose: str | None = Field(default=None, max_length=500)
    context: str | None = Field(default=None, max_length=5000)


class GenerateFollowupDraftOutput(Contract):
    application_id: str = Field(min_length=1, max_length=100)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=5000)
    draft_only: Literal[True] = True
