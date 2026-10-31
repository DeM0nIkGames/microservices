import httpx


class StorageClient:
    def __init__(self, base_url, service_name, service_key):
        self.client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(10.0, connect=3.0), headers={"X-Service-Key": service_key})
        self.service_name = service_name

    def authenticate(self, login: str, password: str):
        response = self.client.post(
            "/auth/login",
            headers={"X-Service-Name": self.service_name},
            json={
                "login": login,
                "password": password,
            },
        )

        if response.status_code == 401: return None
        response.raise_for_status()
        return response.json()

    def get_user_by_id(self, user_id: int):
        response = self.client.get(f"/users/{user_id}", 
                                    headers={
                                       "X-Service-Name": self.service_name
                                    })

        if response.status_code == 404: return None

        response.raise_for_status()
        return response.json()

    def change_password(self, actor_id, user_id, current_password, new_password):
        response = self.client.patch(f"/users/{user_id}/password",
                                     headers={
                                         "X-Service-Name": self.service_name,
                                         "X-Acting-User-Id": actor_id,
                                     },
                                     json={
                                         "current_password": current_password,
                                         "new_password": new_password,
                                     })
        response.raise_for_status()

    def get_users(self, actor_id: int):
        response = self.client.get("/users", 
                                   headers={
                                       "X-Acting-User-Id": str(actor_id),
                                       "X-Service-Name": self.service_name,
                                   })
        response.raise_for_status()
        return response.json()

    def add_user(self, actor_id, login, password, role):
        response = self.client.post("/users",
                                    headers={"X-Service-Name": self.service_name,
                                             "X-Acting-User-Id": str(actor_id),},
                                    json={
                                        "login": login,
                                        "password": password,
                                        "role": role,
                                    })
        response.raise_for_status()

    def update_user(self, actor_id, user_id, login, role, password=None):
        response = self.client.post(f"/users/{user_id}/edit",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    },
                                    json={
                                        "login": login,
                                        "password": password,
                                        "role": role,
                                    })
        response.raise_for_status()

    def get_models(self, actor_id):
        response = self.client.get("/models",
                                   headers={
                                       "X-Acting-User-Id": str(actor_id),
                                       "X-Service-Name": self.service_name,
                                   })
        response.raise_for_status()
        return response.json()

    def get_datasets(self, actor_id):
        response = self.client.get("/datasets",
                                   headers={
                                       "X-Acting-User-Id": str(actor_id),
                                       "X-Service-Name": self.service_name,
                                   })
        response.raise_for_status()
        return response.json()

    def get_runs(self, actor_id):
        response = self.client.get("/results",
                                   headers={
                                       "X-Acting-User-Id": str(actor_id),
                                       "X-Service-Name": self.service_name,
                                   })
        response.raise_for_status()
        return response.json()

    def get_dataset_info(self, actor_id, dataset_id):
        response = self.client.get(f"/datasets/{dataset_id}",
                                   headers={
                                       "X-Service-Name": self.service_name,
                                       "X-Acting-User-Id": str(actor_id),
                                   })
        if response.status_code == 404: return None

        response.raise_for_status()
        return response.json()

    def update_dataset_train_percent(self, actor_id, dataset_id, train_percent):
        response = self.client.post(f"/datasets/{dataset_id}/settings",
                                    headers={
                                        "X-Acting-User-Id": str(actor_id),
                                        "X-Service-Name": self.service_name,
                                    },
                                    json={
                                        "train_percent": train_percent,
                                    })

        response.raise_for_status()

    def rename_class(self, actor_id, dataset_id, class_id, label):
        response = self.client.post(f"/datasets/{dataset_id}/classes/{class_id}",
                                    headers={
                                        "X-Acting-User-Id": str(actor_id),
                                        "X-Service-Name": self.service_name,
                                    },
                                    json={
                                        "label": label,
                                    })
        
        response.raise_for_status()

    def get_model_info(self, actor_id, model_id):
        response = self.client.get(f"/models/{model_id}",
                                   headers={
                                       "X-Service-Name": self.service_name,
                                       "X-Acting-User-Id": str(actor_id),
                                   })
        if response.status_code == 404: return None

        response.raise_for_status()
        return response.json()

    def get_run_info(self, actor_id, run_id):
        response = self.client.get(f"/runs/{run_id}",
                                   headers={
                                       "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                   })
        if response.status_code == 404: return None

        response.raise_for_status()
        return response.json()

    def delete_user(self, actor_id, user_id):
        response = self.client.post(f"/users/{user_id}/delete",
                                    headers={
                                        "X-Acting-User-Id": str(actor_id),
                                        "X-Service-Name": self.service_name,
                                    })
            
        response.raise_for_status()

    def delete_dataset(self, actor_id, dataset_id):
        response = self.client.post(f"/datasets/{dataset_id}/delete",
                                    headers={
                                        "X-Acting-User-Id": str(actor_id),
                                        "X-Service-Name": self.service_name,
                                    })
            
        response.raise_for_status()

    def delete_model(self, actor_id, model_id):
        response = self.client.post(f"/models/{model_id}/delete",
                                    headers={
                                        "X-Acting-User-Id": str(actor_id),
                                        "X-Service-Name": self.service_name,
                                    })
            
        response.raise_for_status()

    def delete_run(self, actor_id, run_id):
        response = self.client.post(f"/runs/{run_id}/delete",
                                    headers={
                                        "X-Acting-User-Id": str(actor_id),
                                        "X-Service-Name": self.service_name,
                                    })
            
        response.raise_for_status()

    def get_model_runs(self, actor_id, model_id):
        response = self.client.get(f"/models/{model_id}/runs",
                                    headers={
                                        "X-Acting-User-Id": str(actor_id),
                                        "X-Service-Name": self.service_name,
                                    })
        
        response.raise_for_status()
        return response.json()

    def revalidate_model(self, actor_id, model_id):
        response = self.client.post(
            f"/models/{model_id}/revalidate",
            headers={
                "X-Service-Name": "web-service",
                "X-Acting-User-Id": str(actor_id),
            },
        )

        response.raise_for_status()
        return response.json()