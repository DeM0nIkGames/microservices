import httpx


class VisClient:
    def __init__(self, base_url, service_name, service_key):
        self.client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(100.0, connect=3.0), headers={"X-Service-Key": service_key})
        self.service_name = service_name

    def get_charts_data(
        self,
        actor_id,
        run_id,
        percentile=95,
        mode="manual",
    ):
        response = self.client.get(f"/runs/{run_id}/charts",
                                    headers={
                                        "X-Service-Name": self.service_name,
                                        "X-Acting-User-Id": str(actor_id),
                                    },
                                    params={
                                        "percentile": percentile,
                                        "mode": mode,
                                    })

        response.raise_for_status()
        return response.json()