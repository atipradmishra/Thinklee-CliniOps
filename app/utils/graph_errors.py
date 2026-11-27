"""Actionable reporting errors without leaking SQL, rows, or credentials."""
from sqlalchemy.exc import SQLAlchemyError
from openai import APIConnectionError, APITimeoutError, RateLimitError


class GraphQueryError(Exception):
    def __init__(self, message, code='query_failed', status=502):
        super().__init__(message)
        self.code, self.status = code, status


def graph_failure(exc, sql=''):
    if isinstance(exc, GraphQueryError):
        message, code, status = str(exc), exc.code, exc.status
    elif isinstance(exc, ValueError):
        message, code, status = str(exc), 'invalid_query', 400
    elif isinstance(exc, (APITimeoutError, TimeoutError)):
        message, code, status = 'Generating this query timed out. Please try again.', 'model_timeout', 504
    elif isinstance(exc, RateLimitError):
        message, code, status = 'The AI service is temporarily rate limited. Please try again shortly.', 'model_rate_limit', 429
    elif isinstance(exc, APIConnectionError):
        message, code, status = 'Cannot reach the AI service. Please try again shortly.', 'model_connection', 503
    elif isinstance(exc, SQLAlchemyError):
        if 'not authorized' in str(exc).lower() or 'prohibited' in str(exc).lower():
            message, code, status = 'This query references data outside the agent\'s assigned tables.', 'table_access_denied', 403
        else:
            message, code, status = 'The generated SQL could not run on this data source. Try rephrasing the question or checking the selected columns.', 'sql_execution', 422
    else:
        message, code, status = 'Unable to generate a query right now. Please try again or check the agent\'s model configuration.', 'query_generation', 502
    return {'sql': sql, 'data': [], 'error': message, 'error_code': code, 'http_status': status}
