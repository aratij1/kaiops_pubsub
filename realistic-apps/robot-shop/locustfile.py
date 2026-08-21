from locust import HttpUser, task, between


class ShopperUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def browse_catalogue(self):
        self.client.get("/api/catalogue/products")

    @task(2)
    def view_product(self):
        self.client.get("/api/catalogue/provduct/837ab141-399e-4c1f-9abc-bace40296bac")

    @task(1)
    def check_cart(self):
        self.client.get("/api/cart/cart/anonymous")

    @task(1)
    def ratings(self):
        self.client.get("/api/ratings/api/fetch/837ab141-399e-4c1f-9abc-bace40296bac")
