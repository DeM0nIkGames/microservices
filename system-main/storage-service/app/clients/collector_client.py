import httpx


class CollectorClient:
    def __init__(self, base_url, service_name, service_key):
        self.client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(30.0, connect=3.0), headers={"X-Service-Key": service_key})
        self.service_name = service_name

    def delete_dataset(self, actor_id, dataset_id, manifest_key):
        response = self.client.request(method="DELETE", url=f"/datasets/{dataset_id}",
                                        headers={
                                            "X-Service-Name": self.service_name,
                                            "X-Acting-User-Id": str(actor_id),
                                        },
                                        json={
                                            "manifest_key": manifest_key,
                                        })

        response.raise_for_status()
        # return response.json()