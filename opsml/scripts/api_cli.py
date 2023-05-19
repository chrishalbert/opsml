import typer
from rich.console import Console
from rich.table import Table

from typing import Annotated, Dict
from opsml.helpers.request_helpers import ApiRoutes, ApiClient
from opsml.registry.sql.settings import settings
from opsml.registry.sql.sql_schema import RegistryTableNames

app = typer.Typer()


def _download_metadata(request_client: ApiClient, payload: Dict[str, str]):
    return request_client.stream_post_request(
        route=ApiRoutes.DOWNLOAD_MODEL_METADATA,
        json=payload,
    )


def _download_model(request_client: ApiClient, filepath: str):
    filepath_split = filepath.split("/")
    filename = filepath_split[-1]
    read_dir = "/".join(filepath_split[:-1])

    request_client.stream_download_file_request(
        route=ApiRoutes.DOWNLOAD_FILE,
        local_dir="models",
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
    name: Annotated[str, typer.Option()] = None,
    team: Annotated[str, typer.Option()] = None,
    version: Annotated[str, typer.Option()] = None,
    uid: Annotated[str, typer.Option()] = None,
    onnx: Annotated[bool, typer.Option()] = True,
):
    if settings.request_client is not None:
        metadata = _download_metadata(
            request_client=settings.request_client,
            payload={"name": name, "version": version, "team": team, "uid": uid},
        )

        if onnx:
            model_path = metadata.get("onnx_uri")
        else:
            model_path = metadata.get("model_uri")

        return _download_model(
            request_client=settings.request_client,
            filepath=model_path,
        )
    else:
        raise ValueError(
            """No HTTP URI detected. Command line client is intended to work directly with HTTP""",
        )


console = Console()


@app.command()
def list_cards(
    registry: Annotated[
        str, typer.Option(help="Registry to search. Accepted values are 'model', 'data', 'pipeline', and 'run'")
    ],
    name: Annotated[str, typer.Option()] = None,
    team: Annotated[str, typer.Option()] = None,
    version: Annotated[str, typer.Option()] = None,
    uid: Annotated[str, typer.Option()] = None,
):
    registry_name = getattr(RegistryTableNames, registry.upper())

    if registry_name is None:
        raise ValueError(
            "No registry found. Accepted values are 'model', 'data', 'pipeline', and 'run'. Found %s",
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


if __name__ == "__main__":
    app()
