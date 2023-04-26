from typing import Any, Awaitable, Callable, Union

import rollbar
from fastapi import Request, Response

from opsml.helpers.logging import ArtifactLogger

logger = ArtifactLogger.get_logger(__name__)

MiddlewareReturnType = Union[Awaitable[Any], Response]


async def rollbar_middleware(
    request: Request, call_next: Callable[[Request], MiddlewareReturnType]
) -> MiddlewareReturnType:
    try:
        return await call_next(request)  # type: ignore
    except Exception:  # pylint: disable=broad-except
        rollbar.report_exc_info()
        logger.exception("unhandled API error")
        return Response("Internal server error", status_code=500)