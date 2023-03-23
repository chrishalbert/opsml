import os
from multiprocessing import Process
from opsml_artifacts.api.main import OpsmlApp
import uvicorn
import requests
import pytest
import time

session = requests.Session()


class TestApp:
    """Test the app class."""

    def __init__(self, is_mlflow: bool):
        self.url = "http://0.0.0.0:8000"
        self.is_mlflow = is_mlflow

    def start(self):
        """Bring server up."""
        app = OpsmlApp(run_mlflow=self.is_mlflow).build_app()
        self.proc = Process(
            target=uvicorn.run,
            args=(app,),
            kwargs={"host": "0.0.0.0", "port": 8000, "log_level": "info"},
            daemon=True,
        )
        self.proc.start()

        running = False
        while not running:
            try:
                response = session.get(f"{self.url}/opsml/healthcheck")
                if response.status_code == 200:
                    running = True
            except Exception as error:
                time.sleep(2)
                pass
        return

    def shutdown(self):
        """Shutdown the app."""
        self.proc.terminate()


# @pytest.fixture(scope="function")
# def test_server():
#    test_app = TestApp()
#
#    test_app.start()
#
#    yield test_app
#
#    test_app.shutdown()


if __name__ == "__main__":

    app = TestApp(is_mlflow=True)
    app.start()