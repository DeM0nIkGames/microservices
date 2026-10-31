import httpx


class StorageClient:
    def __init__(self, base_url, service_name, service_key):
        self.client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(10.0, connect=3.0), headers={"X-Service-Key": service_key})
        self.service_name = service_name

    def check_admin(self, user_id):
        response = self.client.get(f"/users/{user_id}", 
                                    headers={
                                       "X-Service-Name": self.service_name
                                    })
        
        if response.status_code == 404: return False
        
        response.raise_for_status()

        return response.json()["role"] == "admin"

    def create_dataset(self, actor_id, name, manifest_path, class_labels, class_counts, train_percent):
        response = self.client.post("/datasets",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    },
                                    json={
                                        "name": name,
                                        "manifest_path": manifest_path,
                                        "class_labels": class_labels,
                                        "class_counts": class_counts,
                                        "train_percent": train_percent,
                                    })
        response.raise_for_status()
        return response.json()

    def get_manifest_key(self, actor_id, dataset_id):
        response = self.client.get(f"/datasets/{dataset_id}",
                                   headers={
                                       "X-Service-Name": self.service_name,
                                       "X-Acting-User-Id": str(actor_id),
                                   })
        if response.status_code == 404: return None
        
        response.raise_for_status()
        return response.json()["manifest_path"]