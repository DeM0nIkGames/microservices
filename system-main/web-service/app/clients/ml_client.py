import httpx


class MLClient:
    def __init__(self, base_url, service_name, service_key):
        self.client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(200.0, connect=3.0), headers={"X-Service-Key": service_key})
        self.service_name = service_name

    def register_model(self, actor_id, name, version, import_url):
        response = self.client.post("/models",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    },
                                    json={
                                        "name": name,
                                        "version": version,
                                        "import_url": import_url,
                                    })

        response.raise_for_status()
        return response.json()

    def create_run(self, actor_id, model_id, dataset_id, hyperparameters):
        response = self.client.post(f"/models/{model_id}/runs",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    },
                                    json={
                                        "dataset_id": dataset_id,
                                        "hyperparameters": hyperparameters,
                                    })
        
        response.raise_for_status()
        return response.json()

    def get_hyperparameters(self, actor_id, model_id):
        response = self.client.get(f"/models/{model_id}/hyperparameters",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    })
        
        response.raise_for_status()
        return response.json()

    def register_new_version(self, actor_id, model_id, version):
        response = self.client.post(f"/models/{model_id}/versions",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    }, 
                                    json={
                                        "version": version
                                    })
        
        response.raise_for_status()
        return response.json()

    def get_run_progress(self, actor_id, run_id):
        response = self.client.get(f"/runs/{run_id}/progress",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    })
        
        response.raise_for_status()
        return response.json()

    def get_misclassified(self, actor_id, run_id, limit):
        response = self.client.get(f"/runs/{run_id}/misclassified-examples",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    },
                                    params={
                                        "limit_per_pair": limit,
                                    })
        response.raise_for_status()
        return response.json()