"""Sandbox storage and typed tool gateway for the Job Application Tracker."""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel, ValidationError

from app.models import (
	AddApplicationInput,
	AddApplicationOutput,
	Fault,
	GenerateFollowupDraftInput,
	GenerateFollowupDraftOutput,
	JobApplication,
	SearchApplicationsInput,
	SearchApplicationsOutput,
	UpdateApplicationInput,
	UpdateApplicationOutput,
)


class ToolError(Exception):
	"""Controlled error raised internally by a sandbox tool."""

	def __init__(self, code: str, message: str):
		super().__init__(message)
		self.code = code
		self.message = message


class ToolErrorInfo(BaseModel):
	code: str
	message: str


class ToolGatewayResult(BaseModel):
	tool: str
	success: bool
	output: dict[str, Any] | None = None
	error: ToolErrorInfo | None = None


class ToolTimeoutError(ToolError):
	def __init__(self):
		super().__init__('tool_timeout', 'The tool execution timed out.')


class SandboxRepository:
	"""Small in-memory repository seeded from fictional JSON records."""

	def __init__(self, seed_path: str | Path | None = None):
		self._records: dict[str, JobApplication] = {}
		self._next_id = 1
		if seed_path is not None:
			self._load_seed(Path(seed_path))

	def _load_seed(self, seed_path: Path) -> None:
		with seed_path.open(encoding='utf-8') as file:
			payload = json.load(file)
		for raw_record in payload.get('records', []):
			application = JobApplication.model_validate(raw_record)
			if application.application_id in self._records:
				raise ValueError(f'Duplicate seed application ID: {application.application_id}')
			self._records[application.application_id] = application
			self._next_id = max(self._next_id, self._id_number(application.application_id) + 1)

	@staticmethod
	def _id_number(application_id: str) -> int:
		prefix, separator, number = application_id.partition('-')
		if prefix != 'APP' or not separator or not number.isdigit():
			return 0
		return int(number)

	@staticmethod
	def _normalized_pair(company: str, role: str) -> tuple[str, str]:
		return company.strip().casefold(), role.strip().casefold()

	def search(self, request: SearchApplicationsInput) -> SearchApplicationsOutput:
		applications = list(self._records.values())
		if request.application_id is not None:
			applications = [
				application for application in applications
				if application.application_id.casefold() == request.application_id.strip().casefold()
			]
		if request.company is not None:
			company = request.company.strip().casefold()
			applications = [application for application in applications if company in application.company.casefold()]
		if request.role is not None:
			role = request.role.strip().casefold()
			applications = [application for application in applications if role in application.role.casefold()]
		return SearchApplicationsOutput(applications=applications, total_matches=len(applications))

	def snapshot(self) -> tuple[dict[str, JobApplication], int]:
		return self._records.copy(), self._next_id

	def restore(self, snapshot: tuple[dict[str, JobApplication], int]) -> None:
		self._records, self._next_id = snapshot

	def add(self, request: AddApplicationInput) -> AddApplicationOutput:
		normalized_pair = self._normalized_pair(request.company, request.role)
		if any(
			self._normalized_pair(application.company, application.role) == normalized_pair
			for application in self._records.values()
		):
			raise ToolError('duplicate_application', 'An application for this company and role already exists.')
		application_id = f'APP-{self._next_id:03d}'
		self._next_id += 1
		application = JobApplication(application_id=application_id, **request.model_dump())
		self._records[application_id] = application
		return AddApplicationOutput(application=application)

	def update(self, request: UpdateApplicationInput) -> UpdateApplicationOutput:
		current = self._records.get(request.application_id)
		if current is None:
			raise ToolError('missing_record', f'No application exists with ID {request.application_id}.')
		changes = request.model_dump(exclude_unset=True)
		changes.pop('application_id', None)
		if not changes:
			raise ToolError('no_changes', 'The update does not contain any fields to change.')
		candidate = current.model_copy(update=changes)
		updated = JobApplication.model_validate(candidate.model_dump())
		if self._normalized_pair(updated.company, updated.role) != self._normalized_pair(current.company, current.role):
			duplicate = self.search(SearchApplicationsInput(company=updated.company, role=updated.role))
			if any(application.application_id != current.application_id for application in duplicate.applications):
				raise ToolError('duplicate_application', 'The updated company and role already exist.')
		if updated == current:
			raise ToolError('no_changes', 'The update does not change the application.')
		self._records[updated.application_id] = updated
		return UpdateApplicationOutput(application=updated)

	def followup_draft(self, request: GenerateFollowupDraftInput) -> GenerateFollowupDraftOutput:
		application = self._records.get(request.application_id)
		if application is None:
			raise ToolError('missing_record', f'No application exists with ID {request.application_id}.')
		purpose = request.purpose or 'follow up on my application'
		context = f' {request.context.strip()}' if request.context else ''
		return GenerateFollowupDraftOutput(
			application_id=application.application_id,
			subject=f'Follow-up: {application.role} application at {application.company}',
			body=(
				f'Dear {application.company} hiring team,\n\n'
				f'I am writing to {purpose} for the {application.role} position.{context}\n\n'
				'Thank you for your time.\n\nBest regards,\nApplicant'
			),
			draft_only=True,
		)


def search_applications(repository: SandboxRepository, request: SearchApplicationsInput) -> SearchApplicationsOutput:
	return repository.search(request)


def add_application(repository: SandboxRepository, request: AddApplicationInput) -> AddApplicationOutput:
	return repository.add(request)


def update_application(repository: SandboxRepository, request: UpdateApplicationInput) -> UpdateApplicationOutput:
	return repository.update(request)


def generate_followup_draft(
	repository: SandboxRepository, request: GenerateFollowupDraftInput
) -> GenerateFollowupDraftOutput:
	return repository.followup_draft(request)


@dataclass(frozen=True)
class ToolDefinition:
	input_model: type[BaseModel]
	output_model: type[BaseModel]
	handler: Callable[[SandboxRepository, BaseModel], BaseModel]


TOOLS: dict[str, ToolDefinition] = {
	'search_applications': ToolDefinition(SearchApplicationsInput, SearchApplicationsOutput, search_applications),
	'add_application': ToolDefinition(AddApplicationInput, AddApplicationOutput, add_application),
	'update_application': ToolDefinition(UpdateApplicationInput, UpdateApplicationOutput, update_application),
	'generate_followup_draft': ToolDefinition(
		GenerateFollowupDraftInput, GenerateFollowupDraftOutput, generate_followup_draft
	),
}


class ToolGateway:
	"""Validates and dispatches only registered sandbox tools."""

	def __init__(self, repository: SandboxRepository, fault: Fault | None = None):
		self.repository = repository
		self.fault = fault or Fault()
		self._fault_injected = False

	def _inject_fault(self) -> None:
		if self._fault_injected or self.fault.type == 'none':
			return
		if self.fault.type == 'tool_timeout':
			self._fault_injected = True
			raise ToolTimeoutError()

	def dispatch(self, tool_name: str, arguments: dict[str, Any]) -> ToolGatewayResult:
		definition = TOOLS.get(tool_name)
		if definition is None:
			return self._error(tool_name, 'unknown_tool', f'Unknown tool: {tool_name}.')
		try:
			request = definition.input_model.model_validate(arguments)
		except ValidationError as error:
			return self._error(tool_name, 'invalid_arguments', str(error))
		try:
			self._inject_fault()
			snapshot = self.repository.snapshot()
			output = definition.handler(self.repository, request)
			if self.fault.type == 'malformed_tool_output' and not self._fault_injected:
				self._fault_injected = True
				self.repository.restore(snapshot)
				output_data: Any = {'malformed': True}
			else:
				output_data = output.model_dump()
			validated_output = definition.output_model.model_validate(output_data)
			return ToolGatewayResult(tool=tool_name, success=True, output=validated_output.model_dump())
		except ToolError as error:
			return self._error(tool_name, error.code, error.message)
		except ValidationError as error:
			return self._error(tool_name, 'malformed_tool_output', str(error))
		except Exception as error:
			return self._error(tool_name, 'tool_failure', str(error))

	@staticmethod
	def _error(tool_name: str, code: str, message: str) -> ToolGatewayResult:
		return ToolGatewayResult(tool=tool_name, success=False, error=ToolErrorInfo(code=code, message=message))


DATA_PATH = Path(__file__).resolve().parent.parent / 'data' / 'sample_data.json'
default_repository = SandboxRepository(DATA_PATH)
