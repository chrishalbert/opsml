# Copyright (c) Shipt, Inc.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from opsml.app.routes.route_helpers import ProjectRouteHelper
from opsml.app.routes.utils import error_to_500
from opsml.helpers.logging import ArtifactLogger

logger = ArtifactLogger.get_logger()

# Constants
TEMPLATE_PATH = Path(__file__).parents[1] / "templates"
templates = Jinja2Templates(directory=TEMPLATE_PATH)

router = APIRouter()
project_route_helper = ProjectRouteHelper()


@router.get("/projects/list/", response_class=HTMLResponse)
@error_to_500
async def project_list_page(
    request: Request, project: Optional[str] = None, run_uid: Optional[str] = None
) -> HTMLResponse:
    """UI home for listing models in model registry

    Args:
        request:
            The incoming HTTP request.
        project:
            The project to query
        run_uid:
            The run_uid to query

    Returns:
        200 if the request is successful. The body will contain a JSON string
        with the list of models.
    """
    return project_route_helper.get_project_run(request=request, project=project, run_uid=run_uid)  # type: ignore[return-value]


@router.get("/projects/runs/plot/", response_class=HTMLResponse)
@error_to_500
async def project_metric_page(
    request: Request,
    run_uid: str,
) -> HTMLResponse:
    """UI home for listing models in model registry

    Args:
        request:
            The incoming HTTP request.
        run_uid:
            The run_uid to query
    Returns:
        200 if the request is successful. The body will contain a JSON string
        with the list of models.
    """

    return project_route_helper.get_run_metrics(request=request, run_uid=run_uid)  # type: ignore[return-value]
