"""Message storage and session-scoped sandbox state.

This is intentionally in-memory only. Chat history and per-session application data are
lost on server restart, which matches the Assignment 1 one-worker deployment model.
"""
from collections import OrderedDict
from langchain_core.messages import HumanMessage, AIMessage

from app.tools import DATA_PATH, SandboxRepository


class Memory:
    def __init__(self):
        self.sessions = OrderedDict()
        self.repositories = OrderedDict()

    def get(self, session):
        return list(self.sessions.get(session, []))

    def get_session_repository(self, session):
        repository = self.repositories.get(session)
        if repository is None:
            repository = SandboxRepository(DATA_PATH)
            self.repositories[session] = repository
        self.repositories.move_to_end(session)
        return repository

    def has_session(self, session):
        return session in self.sessions or session in self.repositories

    def add(self, session, user, assistant):
        messages = self.get(session) + [HumanMessage(content=user), AIMessage(content=assistant)]
        # Six recent turns; also enforce a character ceiling (not a token counter).
        while len(messages) > 12 or sum(len(str(m.content)) for m in messages) > 24000:
            messages = messages[2:]
        self.sessions[session] = messages
        self.sessions.move_to_end(session)
        while len(self.sessions) > 100:
            self.sessions.popitem(last=False)

    def clear(self, session):
        self.sessions.pop(session, None)
        self.repositories.pop(session, None)
