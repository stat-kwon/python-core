import traceback
import logging
from threading import local

from spaceone.core import utils, config
from spaceone.core.error import *
from opentelemetry import trace
from opentelemetry.trace import format_trace_id
from opentelemetry.trace.span import TraceFlags

__all__ = ['LOCAL_STORAGE', 'get_transaction', 'create_transaction', 'delete_transaction',
           'Transaction']

_LOGGER = logging.getLogger(__name__)
LOCAL_STORAGE = local()


class Transaction(object):

    def __init__(self, resource: str = None, verb: str = None, trace_id: str = None, meta=None):
        self._service = config.get_service()
        self._resource = resource
        self._verb = verb
        self._rollbacks = []
        self._set_meta(meta)
        self._set_trace_id(trace_id)
        self._event_handlers = []

    def __repr__(self):
        return f"<Transaction ({self._resource}.{self._verb})>"

    def _set_trace_id(self, trace_id: str = None) -> None:
        if trace_id:
            self._id = trace_id
        else:
            self._id = format_trace_id(utils.generate_trace_id())

    def _set_meta(self, meta: dict = None):
        if meta:
            self._meta = meta.copy()
        else:
            self._meta = {}

    @property
    def id(self) -> str:
        return self._id

    @property
    def service(self) -> str:
        return self._service

    @property
    def resource(self) -> str:
        return self._resource

    @property
    def verb(self) -> str:
        return self._verb

    def add_rollback(self, fn, *args, **kwargs) -> None:
        self._rollbacks.insert(0, {
            'fn': fn,
            'args': args,
            'kwargs': kwargs
        })

    def execute_rollback(self) -> None:
        for rollback in self._rollbacks:
            try:
                rollback['fn'](*rollback['args'], **rollback['kwargs'])
            except Exception:
                _LOGGER.info(f'[ROLLBACK-ERROR] {self}')
                _LOGGER.info(traceback.format_exc())

    @property
    def meta(self) -> dict:
        return self._meta

    def set_meta(self, key, value) -> None:
        self._meta[key] = value

    def get_meta(self, key, default=None):
        return self._meta.get(key, default)

    def get_connection_meta(self) -> list:
        keys = ['token', 'domain_id']
        result = []
        for key in keys:
            result.append((key, self.get_meta(key)))
        return result

    def notify_event(self, message):
        for handler in self._event_handlers:
            if not isinstance(message, dict):
                message = {'message': str(message)}

            handler.notify(self, 'IN_PROGRESS', message)


def get_transaction(trace_id: str = None, is_create: bool = True) -> [Transaction, None]:
    current_span_context = trace.get_current_span().get_span_context()

    if current_span_context.trace_flags == TraceFlags.SAMPLED:
        trace_id_from_current_span = format_trace_id(current_span_context.trace_id)
        return getattr(LOCAL_STORAGE, trace_id_from_current_span, None)
    elif trace_id:
        return getattr(LOCAL_STORAGE, trace_id, None)
    elif is_create:
        return create_transaction()
    else:
        return None


def create_transaction(resource: str = None, verb: str = None, trace_id: str = None,
                       meta: dict = None) -> Transaction:
    transaction = Transaction(resource, verb, trace_id, meta)
    setattr(LOCAL_STORAGE, transaction.id, transaction)
    return transaction


def delete_transaction() -> None:
    if transaction := get_transaction(is_create=False):
        if hasattr(LOCAL_STORAGE, transaction.id):
            delattr(LOCAL_STORAGE, transaction.id)
