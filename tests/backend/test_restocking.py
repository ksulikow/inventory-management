"""
Tests for restocking API endpoints.

Note: POST /api/restocking/orders mutates the shared in-memory orders/inventory
lists for the rest of the test session (no persistence layer to reset between
tests). Recommendation-list assertions run first in this file, before any
order-creation test changes the underlying inventory quantities.
"""
import pytest


class TestRestockingRecommendations:
    """Test suite for GET /api/restocking/recommendations."""

    def test_get_recommendations(self, client):
        """Test getting restock recommendations."""
        response = client.get("/api/restocking/recommendations")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_recommendation_structure(self, client):
        """Test that each recommendation has the expected fields."""
        response = client.get("/api/restocking/recommendations")
        data = response.json()

        for item in data:
            assert "sku" in item
            assert "item_name" in item
            assert "category" in item
            assert "warehouse" in item
            assert "unit_cost" in item
            assert "quantity_on_hand" in item
            assert "reorder_point" in item
            assert "trend" in item
            assert "lead_time_days" in item
            assert "suggested_quantity" in item
            assert "line_total" in item

    def test_recommendations_only_include_shortfall_items(self, client):
        """Test that every recommendation has a positive suggested quantity."""
        response = client.get("/api/restocking/recommendations")
        data = response.json()

        for item in data:
            assert item["suggested_quantity"] > 0
            assert item["forecasted_demand"] > item["quantity_on_hand"]

    def test_recommendations_sorted_by_priority(self, client):
        """Test that increasing-trend items are ranked ahead of stable/decreasing ones."""
        response = client.get("/api/restocking/recommendations")
        data = response.json()

        trend_rank = {"increasing": 0, "stable": 1, "decreasing": 2}
        ranks = [trend_rank.get(item["trend"], 1) for item in data]
        assert ranks == sorted(ranks)

    def test_recommendation_line_total_calculation(self, client):
        """Test that line_total matches suggested_quantity * unit_cost."""
        response = client.get("/api/restocking/recommendations")
        data = response.json()

        for item in data:
            expected_total = item["suggested_quantity"] * item["unit_cost"]
            assert abs(item["line_total"] - expected_total) < 0.01


class TestRestockingOrders:
    """Test suite for POST /api/restocking/orders."""

    def test_create_restock_order(self, client):
        """Test submitting a restock order for a recommended item."""
        recommendations = client.get("/api/restocking/recommendations").json()
        target = recommendations[0]

        response = client.post(
            "/api/restocking/orders",
            json={"items": [{"sku": target["sku"], "quantity": target["suggested_quantity"]}]}
        )
        assert response.status_code == 201

        order = response.json()
        assert order["source"] == "restock"
        assert order["status"] == "Processing"
        assert order["lead_time_days"] == target["lead_time_days"]
        assert order["order_number"].startswith("RST-2025-")
        assert len(order["items"]) == 1
        assert order["items"][0]["sku"] == target["sku"]
        assert order["items"][0]["quantity"] == target["suggested_quantity"]

        expected_total = target["suggested_quantity"] * target["unit_cost"]
        assert abs(order["total_value"] - expected_total) < 0.01

    def test_restock_order_increments_inventory(self, client):
        """Test that placing a restock order increases quantity_on_hand for the SKU."""
        inventory_before = {i["sku"]: i for i in client.get("/api/inventory").json()}
        sku = "TMP-201"
        qty_before = inventory_before[sku]["quantity_on_hand"]

        response = client.post(
            "/api/restocking/orders",
            json={"items": [{"sku": sku, "quantity": 50}]}
        )
        assert response.status_code == 201

        inventory_after = {i["sku"]: i for i in client.get("/api/inventory").json()}
        assert inventory_after[sku]["quantity_on_hand"] == qty_before + 50

    def test_restock_order_appears_in_orders_list(self, client):
        """Test that a submitted restock order shows up via GET /api/orders."""
        response = client.post(
            "/api/restocking/orders",
            json={"items": [{"sku": "ACC-206", "quantity": 2}]}
        )
        order_number = response.json()["order_number"]

        all_orders = client.get("/api/orders").json()
        matching = [o for o in all_orders if o["order_number"] == order_number]
        assert len(matching) == 1
        assert matching[0]["source"] == "restock"

    def test_create_restock_order_unknown_sku(self, client):
        """Test that an unknown SKU returns 404."""
        response = client.post(
            "/api/restocking/orders",
            json={"items": [{"sku": "NOT-A-REAL-SKU", "quantity": 1}]}
        )
        assert response.status_code == 404

    def test_create_restock_order_invalid_quantity(self, client):
        """Test that a non-positive quantity returns 400."""
        response = client.post(
            "/api/restocking/orders",
            json={"items": [{"sku": "TMP-201", "quantity": 0}]}
        )
        assert response.status_code == 400

    def test_create_restock_order_empty_items(self, client):
        """Test that an empty items list returns 400."""
        response = client.post("/api/restocking/orders", json={"items": []})
        assert response.status_code == 400
