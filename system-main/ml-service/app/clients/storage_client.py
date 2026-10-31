import httpx


class StorageClient:
    def __init__(self, base_url, service_name, service_key):
        self.client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(10.0, connect=3.0), headers={"X-Service-Key": service_key})
        self.service_name = service_name

    def _headers(self, actor_id=None):
        headers = {"X-Service-Name": self.service_name}
        if actor_id is not None: headers["X-Acting-User-Id"] = str(actor_id)
        return headers

    def check_admin(self, user_id):
        response = self.client.get(f"/users/{user_id}", 
                                   headers={"X-Service-Name": self.service_name})
        response.raise_for_status()
        return response.json()["role"] == "admin"

    def create_model(self, actor_id, name, version, import_url):
        response = self.client.post("/models",
                                    headers=self._headers(actor_id),
                                    json={
                                        "name": name,
                                        "version": version,
                                        "import_url": import_url,
                                    })
        response.raise_for_status()
        return response.json()

    def get_hyperparams(self, actor_id, model_id):
        response = self.client.get(f"/models/{model_id}/hyperparameters",
                                    headers=self._headers(actor_id))
        response.raise_for_status()
        return response.json()

    def register_version(self, actor_id, model_id, version):
        response = self.client.post(f"/models/{model_id}/versions",
                                    headers=self._headers(actor_id),
                                    json={"version": version})
        response.raise_for_status()
        return response.json()

    def create_run(self, actor_id, model_id, dataset_id, hyperparameters):
        response = self.client.post(f"/models/{model_id}/runs",
                                    headers=self._headers(actor_id),
                                    json={
                                        "dataset_id": dataset_id,
                                        "hyperparameters": hyperparameters,
                                    })
        response.raise_for_status()
        return response.json()

    def request_run_cancel(self, actor_id, run_id):
        response = self.client.post(f"/runs/{run_id}/cancel",
                                    headers=self._headers(actor_id),)
        response.raise_for_status()
        return response.json()

    def get_progress(self, actor_id, run_id):
        response = self.client.get(f"/runs/{run_id}/progress",
                                    headers=self._headers(actor_id),)
        response.raise_for_status()
        return response.json()

    def get_model_info(self, actor_id, model_id):
        response = self.client.get(f"/models/{model_id}",
                                    headers=self._headers(actor_id))
        response.raise_for_status()
        return response.json()

    def get_dataset_info(self, actor_id, dataset_id):
        response = self.client.get(f"/datasets/{dataset_id}",
                                    headers=self._headers(actor_id))
        response.raise_for_status()
        return response.json()

    def claim_next_model_validation(self, worker_id):
        response = self.client.post("/internal/models/claim-validation",
                                    headers=self._headers(),
                                    json={"worker_id": worker_id})
        
        if response.status_code == 204: return None
        response.raise_for_status()
        return response.json()

    def add_metadata(self, model_id, metadata):
        response = self.client.patch(f"/internal/models/{model_id}/metadata",
                                    headers=self._headers(),
                                    json={"metadata": metadata})
        response.raise_for_status()

    def update_model_status(self, model_id, status, error_message=None):
        response = self.client.patch(f"/internal/models/{model_id}/status",
                                    headers=self._headers(),
                                    json={
                                        "status": status,
                                        "error_message": error_message,
                                    })
        response.raise_for_status()

    def claim_next_run(self, worker_id):
        response = self.client.post("/internal/runs/claim",
                                    headers=self._headers(),
                                    json={"worker_id": worker_id})

        if response.status_code == 204: return None
        response.raise_for_status()
        return response.json()

    def get_run_for_worker(self, run_id):
        response = self.client.get(f"/internal/runs/{run_id}",
                                    headers=self._headers())
        response.raise_for_status()
        return response.json()

    def update_run_progress(self, run_id, progress):
        response = self.client.patch(f"/internal/runs/{run_id}/progress",
                                    headers=self._headers(),
                                    json={"progress": progress})
        response.raise_for_status()

    def complete_run(self, run_id, metrics, results_path):
        response = self.client.post(f"/internal/runs/{run_id}/complete",
                                    headers=self._headers(),
                                    json={
                                        "metrics": metrics,
                                        "results_path": results_path,
                                    })
        response.raise_for_status()

    def mark_run_cancelled(self, run_id):
        response = self.client.post(f"/internal/runs/{run_id}/cancelled",
                                    headers=self._headers())
        response.raise_for_status()

    def fail_run(self, run_id, error_message):
        response = self.client.post(f"/internal/runs/{run_id}/fail",
                                    headers=self._headers(),
                                    json={"error_message": error_message})
        response.raise_for_status()

    def get_run_info(self, actor_id, run_id):
        response = self.client.get(f"/runs/{run_id}",
                                    headers=self._headers(actor_id))

        if response.status_code == 404: return None
        response.raise_for_status()
        return response.json()