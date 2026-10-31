import logging
import os
import socket
import threading

import httpx

from app import create_app
from app.models.validator import ModelValidator
from app.models.model_pipeline import model_cycle, CancellationError


POLL_INTERVAL_SECONDS = 2


class MLWorker:
    def __init__(self, app):
        self.app = app
        self.stop_event = threading.Event()
        self.worker_id = (os.getenv("WORKER_ID") or socket.gethostname())

    def run_loop(self):
        with self.app.app_context():
            storage = self.app.extensions["storage_client"]

            while not self.stop_event.is_set():
                try:
                    model = storage.claim_next_model_validation(
                        worker_id=self.worker_id,
                    )

                    if model is not None:
                        self._validate_model(model)
                        continue

                    run = storage.claim_next_run(
                        worker_id=self.worker_id,
                    )

                    if run is not None:
                        self._execute_run(run)
                        continue

                except httpx.RequestError:
                    self.app.logger.exception(
                        "Storage временно недоступен для ML-worker."
                    )
                except Exception:
                    self.app.logger.exception(
                        "Необработанная ошибка ML-worker."
                    )

                self.stop_event.wait(POLL_INTERVAL_SECONDS)

    def _validate_model(self, model):
        storage = self.app.extensions["storage_client"]
        validator = ModelValidator(
            model_url=model["import_url"],
            expected_name=model["name"],
            expected_version=model["version"],
        )

        try:
            metadata = validator.validate()
            storage.add_metadata(model_id=model["id"], metadata=metadata)

        except (httpx.HTTPError, ValueError) as error:
            self.app.logger.warning(
                "Валидация модели %s не прошла: %s",
                model["id"],
                error,
            )

            storage.update_model_status(
                model_id=model["id"],
                status="failed",
                error_message=str(error),
            )

        else:
            storage.update_model_status(
                model_id=model["id"],
                status="validated",
            )

        finally:
            validator.close()

    def _execute_run(self, run):
        storage = self.app.extensions["storage_client"]

        try:
            self.run_training_pipeline(run)
        except CancellationError:
            self.app.logger.exception(
                "Запуск %s был отменён.",
                run["id"],
            )

            storage.mark_run_cancelled(run_id=run["id"])
            
        except Exception as error:
            self.app.logger.exception(
                "Запуск %s завершился ошибкой.",
                run["id"],
            )

            storage.fail_run(
                run_id=run["id"],
                error_message=str(error),
            )

    def run_training_pipeline(self, run):
        model_cycle(run["id"])
        

def main():
    app = create_app()
    worker = MLWorker(app)

    try:
        worker.run_loop()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()