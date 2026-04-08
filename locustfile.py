import uuid
import random
from locust import HttpUser, task, between

class OrderUser(HttpUser):
    # simulates a user thinking for 1-2 seconds between actions
    wait_time = between(1, 2)
    # list to store created order ids for get_orders API test task
    created_ids = []

    @task(2)
    def create_order(self):
        # generate request with randomized Idempotency-Key value
        """Tests POST /orders with Idempotency"""
        payload = {
            "customer_id": f"cust-{random.randint(1, 100)}",
            "item_id": "item-arm64",
            "quantity": random.randint(1, 10)
        }
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        
        # if status code is 201, set as successful
        # add order_id to list of available order id values
        with self.client.post("/orders", json=payload, headers=headers, catch_response=True) as response:
            if response.status_code == 201:
                oid = response.json().get("order_id")
                if oid:
                    self.created_ids.append(oid)
                response.success()
            else:
                # this marks the request as a failure in the Locust UI
                response.failure(f"Got {response.status_code}: {response.text}")

    @task(1)
    def get_order_status(self):
        """Tests GET /orders/<id>"""
        # test get_orders API with a randomized available order_id value
        if self.created_ids:
            oid = random.choice(self.created_ids)
            self.client.get(f"/orders/{oid}", name="/orders/[id]")
        else:
            # test 404 logic if no orders exist yet
            self.client.get("/orders/99999", name="/orders/[id]")