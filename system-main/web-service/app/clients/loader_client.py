import httpx


class CollectorClient:
    def __init__(self, base_url, service_name, service_key):
        self.client = httpx.Client(base_url=base_url, timeout=httpx.Timeout(200.0, connect=3.0), headers={"X-Service-Key": service_key})
        self.service_name = service_name

    def create_dataset(self, actor_id, name, archive, default_train_percent):
        response = self.client.post("/datasets",
                                    headers={
                                        "X-Acting-User-Id": str(actor_id),
                                        "X-Service-Name": self.service_name,
                                    },
                                    data={
                                        "name": name,
                                        "default_train_percent": default_train_percent,
                                    },
                                    files={
                                        "archive": (
                                            archive.filename,
                                            archive.stream,
                                            archive.mimetype or "application/zip")
                                    })

        response.raise_for_status()
        return response.json()

    def get_preview_urls(self, actor_id, dataset_id):
        response = self.client.get(f"/datasets/{dataset_id}/preview",
                                   headers={
                                       "X-Acting-User-Id": str(actor_id),
                                       "X-Service-Name": self.service_name,
                                   })

        response.raise_for_status()
        return response.json()["preview_urls"]

    def get_image_urls(self, actor_id, dataset_id, item_ids):
        response = self.client.post(f"/datasets/{dataset_id}/image-urls",
                                    headers={
                                        "X-Acting-User-Id": str(actor_id),
                                        "X-Service-Name": self.service_name,
                                    },
                                    json={
                                        "item_ids": item_ids,
                                    })

        response.raise_for_status()
        return response.json()["items"]