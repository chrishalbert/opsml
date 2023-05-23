import json
import pathlib
from typing import Any, Dict

import typer
from rich.console import Console
from rich.table import Table

from opsml.helpers.logging import ArtifactLogger
from opsml.helpers.request_helpers import ApiClient, ApiRoutes
from opsml.registry.sql.settings import settings
from opsml.registry.sql.sql_schema import RegistryTableNames

logger = ArtifactLogger.get_logger(__name__)

app = typer.Typer()

_METADATA_FILENAME = "metadata.json"


def _download_metadata(request_client: ApiClient, payload: Dict[str, str], path: pathlib.Path) -> Dict[str, Any]:
    """
    Loads and saves model metadata

    Args:
        request_client:
            `ApiClient`
        payload:
            Payload to pass to request client
        path:
            Pathlib path to save response to

    Returns:
        Dictionary of metadata
    """

    metadata = request_client.stream_post_request(
        route=ApiRoutes.DOWNLOAD_MODEL_METADATA,
        json=payload,
    )

    metadata_path = path / _METADATA_FILENAME
    logger.info("saving metadata to %s", str(metadata_path))
    metadata_path.write_text(json.dumps(metadata, indent=4))

    return metadata


def _download_model(request_client: ApiClient, filepath: str, write_path: pathlib.Path) -> None:
    """
    Downloads model file to directory

    Args:
        request_client:
            `ApiClient`
        filepath:
            External model filepath
        write_path:
            Path to write file to

    """

    filepath_split = filepath.split("/")
    filename = filepath_split[-1]
    read_dir = "/".join(filepath_split[:-1])

    logger.info("saving model to %s", str(write_path))
    request_client.stream_download_file_request(
        route=ApiRoutes.DOWNLOAD_FILE,
        local_dir=str(write_path),
        filename=filename,
        read_dir=read_dir,
    )


def _list_cards(request_client: ApiClient, payload: Dict[str, str]):
    response = request_client.post_request(
        route=ApiRoutes.LIST_CARDS,
        json=payload,
    )

    return response.get("cards")


@app.command()
def download_model(
    name: str = typer.Option(default=None),
    team: str = typer.Option(default=None),
    version: str = typer.Option(default=None),
    uid: str = typer.Option(default=None),
    onnx: bool = typer.Option(default=True),
    write_dir: str = typer.Option(default=None),
):
    """
    Downloads a model (onnx or original model) associated with a model card

    Args:
        name:
            Card name
        team:
            Team name
        version:
            Version to search
        uid:
            Uid of Card
        onnx:
            Whether to return onnx model or original model (no-onnx)
        write_dir:
            Director to write to

    Example:
        opsml-api download-model --name "linear-reg" --team "mlops" --write_dir ".models" --no-onnx # original model
        opsml-api download-model --name "linear-reg" --team "mlops" --write_dir ".models" --onnx # onnx model
        opsml-api download-model --name "linear-reg" --team "mlops" --version "1.0.0" --write_dir ".models"

    """

    if settings.request_client is not None:
        path = pathlib.Path(write_dir)
        path.mkdir(parents=True, exist_ok=True)

        metadata = _download_metadata(
            request_client=settings.request_client,
            payload={"name": name, "version": version, "team": team, "uid": uid},
            path=path,
        )

        if onnx:
            model_path = str(metadata.get("onnx_uri"))
        else:
            model_path = str(metadata.get("model_uri"))

        return _download_model(
            request_client=settings.request_client,
            filepath=model_path,
            write_path=path,
        )
    raise ValueError(
        """No HTTP URI detected. Command line client is intended to work directly with HTTP""",
    )


console = Console()


@app.command()
def list_cards(
    registry: str = typer.Option(
        ..., help="Registry to search. Accepted values are 'model', 'data', 'pipeline', and 'run'"
    ),
    name: str = typer.Option(default=None),
    team: str = typer.Option(default=None),
    version: str = typer.Option(default=None),
    uid: str = typer.Option(default=None),
):
    """
    Lists cards from a specific registry in table format

    Args:
        registry:
            Name of Card registry to search. Accepted values are 'model', 'data', 'pipeline', and 'run'
        name:
            Card name
        team:
            Team name
        version:
            Version to search
        uid:
            Uid of Card

    Example:
        opsml-api list-card --name "linear-reg" --team "mlops"

    """
    registry_name = getattr(RegistryTableNames, registry.upper())

    if registry_name is None:
        raise ValueError(
            f"No registry found. Accepted values are 'model', 'data', 'pipeline', and 'run'. Found {registry}",
            registry,
        )
    if settings.request_client is not None:
        cards = _list_cards(
            request_client=settings.request_client,
            payload={
                "name": name,
                "version": version,
                "team": team,
                "uid": uid,
                "table_name": registry_name,
            },
        )

        table = Table(title=f"{registry_name} cards")
        table.add_column("Name", no_wrap=True)
        table.add_column("Team")
        table.add_column("Date")
        table.add_column("User Email")
        table.add_column("Version")
        table.add_column("Uid", justify="right")

        for card in cards:
            table.add_row(
                card.get("name"),
                card.get("team"),
                card.get("date"),
                card.get("user_email"),
                card.get("version"),
                card.get("uid"),
            )
        console.print(table)

    else:
        raise ValueError(
            """No HTTP URI detected. Command line client is intended to work directly with HTTP""",
        )


@app.command()
def launch_server():
    typer.launch(settings.opsml_tracking_uri)


if __name__ == "__main__":
    app()
