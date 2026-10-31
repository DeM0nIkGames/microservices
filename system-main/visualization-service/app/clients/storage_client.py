import httpx


class StorageClient:
    def __init__(self, base_url, service_name, service_key):
        self.client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(10.0, connect=3.0), headers={"X-Service-Key": service_key})
        self.service_name = service_name

    def get_run_info(self, actor_id, run_id):
        response = self.client.get(f"/runs/{run_id}",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    })

        if response.status_code == 404: return None
        response.raise_for_status()
        return response.json()