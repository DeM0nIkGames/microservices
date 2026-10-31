import httpx


class CollectorClient:
    def __init__(self, base_url, service_name, service_key):
        self.client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(200.0, connect=3.0), headers={"X-Service-Key": service_key})
        self.service_name = service_name

    def get_manifest(self, actor_id, dataset_id):
        response = self.client.get(f"/datasets/{dataset_id}/manifest",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    })
        response.raise_for_status()
        return response.json()

    def get_batch(self, actor_id, dataset_id, item_ids):
        response = self.client.post(f"/datasets/{dataset_id}/batch",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    }, json={"item_ids": item_ids})
        response.raise_for_status()
        return response.json()

    