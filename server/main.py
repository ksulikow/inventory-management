from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from datetime import datetime, timedelta
from uuid import uuid4
from pydantic import BaseModel
from mock_data import inventory_items, orders, demand_forecasts, backlog_items, spending_summary, monthly_spending, category_spending, recent_transactions, purchase_orders

app = FastAPI(title="Factory Inventory Management System")

# Quarter mapping for date filtering
QUARTER_MAP = {
    'Q1-2025': ['2025-01', '2025-02', '2025-03'],
    'Q2-2025': ['2025-04', '2025-05', '2025-06'],
    'Q3-2025': ['2025-07', '2025-08', '2025-09'],
    'Q4-2025': ['2025-10', '2025-11', '2025-12']
}

def filter_by_month(items: list, month: Optional[str]) -> list:
    """Filter items by month/quarter based on order_date field"""
    if not month or month == 'all':
        return items

    if month.startswith('Q'):
        # Handle quarters
        if month in QUARTER_MAP:
            months = QUARTER_MAP[month]
            return [item for item in items if any(m in item.get('order_date', '') for m in months)]
    else:
        # Direct month match
        return [item for item in items if month in item.get('order_date', '')]

    return items

def apply_filters(items: list, warehouse: Optional[str] = None, category: Optional[str] = None,
                 status: Optional[str] = None) -> list:
    """Apply common filters to a list of items"""
    filtered = items

    if warehouse and warehouse != 'all':
        filtered = [item for item in filtered if item.get('warehouse') == warehouse]

    if category and category != 'all':
        filtered = [item for item in filtered if item.get('category', '').lower() == category.lower()]

    if status and status != 'all':
        filtered = [item for item in filtered if item.get('status', '').lower() == status.lower()]

    return filtered

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Data models
class InventoryItem(BaseModel):
    id: str
    sku: str
    name: str
    category: str
    warehouse: str
    quantity_on_hand: int
    reorder_point: int
    unit_cost: float
    lead_time_days: int
    location: str
    last_updated: str

class Order(BaseModel):
    id: str
    order_number: str
    customer: str
    items: List[dict]
    status: str
    order_date: str
    expected_delivery: str
    total_value: float
    actual_delivery: Optional[str] = None
    warehouse: Optional[str] = None
    category: Optional[str] = None
    source: Optional[str] = None
    lead_time_days: Optional[int] = None

class DemandForecast(BaseModel):
    id: str
    item_sku: str
    item_name: str
    current_demand: int
    forecasted_demand: int
    trend: str
    period: str

class BacklogItem(BaseModel):
    id: str
    order_id: str
    item_sku: str
    item_name: str
    quantity_needed: int
    quantity_available: int
    days_delayed: int
    priority: str
    has_purchase_order: Optional[bool] = False

class PurchaseOrder(BaseModel):
    id: str
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    status: str
    created_date: str
    notes: Optional[str] = None

class CreatePurchaseOrderRequest(BaseModel):
    backlog_item_id: str
    supplier_name: str
    quantity: int
    unit_cost: float
    expected_delivery_date: str
    notes: Optional[str] = None

class RestockRecommendation(BaseModel):
    sku: str
    item_name: str
    category: str
    warehouse: str
    unit_cost: float
    quantity_on_hand: int
    reorder_point: int
    current_demand: int
    forecasted_demand: int
    trend: str
    lead_time_days: int
    suggested_quantity: int
    line_total: float

class RestockOrderItem(BaseModel):
    sku: str
    quantity: int

class CreateRestockOrderRequest(BaseModel):
    items: List[RestockOrderItem]

# API endpoints
@app.get("/")
def root():
    return {"message": "Factory Inventory Management System API", "version": "1.0.0"}

@app.get("/api/inventory", response_model=List[InventoryItem])
def get_inventory(
    warehouse: Optional[str] = None,
    category: Optional[str] = None
):
    """Get all inventory items with optional filtering"""
    return apply_filters(inventory_items, warehouse, category)

@app.get("/api/inventory/{item_id}", response_model=InventoryItem)
def get_inventory_item(item_id: str):
    """Get a specific inventory item"""
    item = next((item for item in inventory_items if item["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item

@app.get("/api/orders", response_model=List[Order])
def get_orders(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get all orders with optional filtering"""
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)
    return filtered_orders

@app.get("/api/orders/{order_id}", response_model=Order)
def get_order(order_id: str):
    """Get a specific order"""
    order = next((order for order in orders if order["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order

@app.get("/api/demand", response_model=List[DemandForecast])
def get_demand_forecasts():
    """Get demand forecasts"""
    return demand_forecasts

@app.get("/api/backlog", response_model=List[BacklogItem])
def get_backlog():
    """Get backlog items with purchase order status"""
    # Add has_purchase_order flag to each backlog item
    result = []
    for item in backlog_items:
        item_dict = dict(item)
        # Check if this backlog item has a purchase order
        has_po = any(po["backlog_item_id"] == item["id"] for po in purchase_orders)
        item_dict["has_purchase_order"] = has_po
        result.append(item_dict)
    return result

TREND_PRIORITY = {"increasing": 0, "stable": 1, "decreasing": 2}

@app.get("/api/restocking/recommendations", response_model=List[RestockRecommendation])
def get_restocking_recommendations():
    """Recommend items to restock based on demand forecasts outpacing on-hand inventory"""
    inventory_by_sku = {item["sku"]: item for item in inventory_items}
    recommendations = []

    for forecast in demand_forecasts:
        inventory_item = inventory_by_sku.get(forecast["item_sku"])
        if not inventory_item:
            continue

        suggested_quantity = max(forecast["forecasted_demand"] - inventory_item["quantity_on_hand"], 0)
        if suggested_quantity <= 0:
            continue

        recommendations.append(RestockRecommendation(
            sku=inventory_item["sku"],
            item_name=inventory_item["name"],
            category=inventory_item["category"],
            warehouse=inventory_item["warehouse"],
            unit_cost=inventory_item["unit_cost"],
            quantity_on_hand=inventory_item["quantity_on_hand"],
            reorder_point=inventory_item["reorder_point"],
            current_demand=forecast["current_demand"],
            forecasted_demand=forecast["forecasted_demand"],
            trend=forecast["trend"],
            lead_time_days=inventory_item["lead_time_days"],
            suggested_quantity=suggested_quantity,
            line_total=round(suggested_quantity * inventory_item["unit_cost"], 2)
        ))

    recommendations.sort(key=lambda r: (TREND_PRIORITY.get(r.trend, 1), -r.suggested_quantity))
    return recommendations

@app.post("/api/restocking/orders", response_model=Order, status_code=201)
def create_restock_order(request: CreateRestockOrderRequest):
    """Submit a restocking order for the given items, sourced from restocking recommendations"""
    if not request.items:
        raise HTTPException(status_code=400, detail="At least one item is required")

    inventory_by_sku = {item["sku"]: item for item in inventory_items}
    order_items = []
    max_lead_time = 0

    for requested in request.items:
        inventory_item = inventory_by_sku.get(requested.sku)
        if not inventory_item:
            raise HTTPException(status_code=404, detail=f"Unknown SKU: {requested.sku}")
        if requested.quantity <= 0:
            raise HTTPException(status_code=400, detail=f"Quantity for {requested.sku} must be positive")

        order_items.append({
            "sku": inventory_item["sku"],
            "name": inventory_item["name"],
            "quantity": requested.quantity,
            "unit_price": inventory_item["unit_cost"]
        })
        max_lead_time = max(max_lead_time, inventory_item["lead_time_days"])

        # Increment on-hand stock immediately to simulate the restock being committed
        inventory_item["quantity_on_hand"] += requested.quantity

    # Base the new order off the most recent existing order date, keeping it within the
    # dataset's Sept 2025 timeline instead of jumping to the real current date
    latest_order_date = max(datetime.fromisoformat(o["order_date"]) for o in orders)
    expected_delivery = latest_order_date + timedelta(days=max_lead_time)

    restock_order_count = len([o for o in orders if o.get("source") == "restock"])
    total_value = round(sum(item["quantity"] * item["unit_price"] for item in order_items), 2)

    new_order = {
        "id": f"restock-{uuid4().hex[:8]}",
        "order_number": f"RST-2025-{restock_order_count + 1:04d}",
        "customer": "Internal Restocking",
        "items": order_items,
        "status": "Processing",
        "order_date": latest_order_date.isoformat(),
        "expected_delivery": expected_delivery.isoformat(),
        "total_value": total_value,
        "actual_delivery": None,
        "warehouse": None,
        "category": None,
        "source": "restock",
        "lead_time_days": max_lead_time
    }

    orders.append(new_order)
    return new_order

@app.get("/api/dashboard/summary")
def get_dashboard_summary(
    warehouse: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    month: Optional[str] = None
):
    """Get summary statistics for dashboard with optional filtering"""
    # Filter inventory
    filtered_inventory = apply_filters(inventory_items, warehouse, category)

    # Filter orders
    filtered_orders = apply_filters(orders, warehouse, category, status)
    filtered_orders = filter_by_month(filtered_orders, month)

    total_inventory_value = sum(item["quantity_on_hand"] * item["unit_cost"] for item in filtered_inventory)
    low_stock_items = len([item for item in filtered_inventory if item["quantity_on_hand"] <= item["reorder_point"]])
    pending_orders = len([order for order in filtered_orders if order["status"] in ["Processing", "Backordered"]])
    total_backlog_items = len(backlog_items)

    return {
        "total_inventory_value": round(total_inventory_value, 2),
        "low_stock_items": low_stock_items,
        "pending_orders": pending_orders,
        "total_backlog_items": total_backlog_items,
        "total_orders_value": sum(order["total_value"] for order in filtered_orders)
    }

@app.get("/api/spending/summary")
def get_spending_summary():
    """Get spending summary statistics"""
    return spending_summary

@app.get("/api/spending/monthly")
def get_monthly_spending():
    """Get monthly spending breakdown"""
    return monthly_spending

@app.get("/api/spending/categories")
def get_category_spending():
    """Get spending by category"""
    return category_spending

@app.get("/api/spending/transactions")
def get_recent_transactions():
    """Get recent transactions"""
    return recent_transactions

@app.get("/api/reports/quarterly")
def get_quarterly_reports():
    """Get quarterly performance reports"""
    # Calculate quarterly statistics from orders
    quarters = {}

    for order in orders:
        order_date = order.get('order_date', '')
        # Determine quarter
        if '2025-01' in order_date or '2025-02' in order_date or '2025-03' in order_date:
            quarter = 'Q1-2025'
        elif '2025-04' in order_date or '2025-05' in order_date or '2025-06' in order_date:
            quarter = 'Q2-2025'
        elif '2025-07' in order_date or '2025-08' in order_date or '2025-09' in order_date:
            quarter = 'Q3-2025'
        elif '2025-10' in order_date or '2025-11' in order_date or '2025-12' in order_date:
            quarter = 'Q4-2025'
        else:
            continue

        if quarter not in quarters:
            quarters[quarter] = {
                'quarter': quarter,
                'total_orders': 0,
                'total_revenue': 0,
                'delivered_orders': 0,
                'avg_order_value': 0
            }

        quarters[quarter]['total_orders'] += 1
        quarters[quarter]['total_revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            quarters[quarter]['delivered_orders'] += 1

    # Calculate averages and fulfillment rate
    result = []
    for q, data in quarters.items():
        if data['total_orders'] > 0:
            data['avg_order_value'] = round(data['total_revenue'] / data['total_orders'], 2)
            data['fulfillment_rate'] = round((data['delivered_orders'] / data['total_orders']) * 100, 1)
        result.append(data)

    # Sort by quarter
    result.sort(key=lambda x: x['quarter'])
    return result

@app.get("/api/reports/monthly-trends")
def get_monthly_trends():
    """Get month-over-month trends"""
    months = {}

    for order in orders:
        order_date = order.get('order_date', '')
        if not order_date:
            continue

        # Extract month (format: YYYY-MM-DD)
        month = order_date[:7]  # Gets YYYY-MM

        if month not in months:
            months[month] = {
                'month': month,
                'order_count': 0,
                'revenue': 0,
                'delivered_count': 0
            }

        months[month]['order_count'] += 1
        months[month]['revenue'] += order.get('total_value', 0)
        if order.get('status') == 'Delivered':
            months[month]['delivered_count'] += 1

    # Convert to list and sort
    result = list(months.values())
    result.sort(key=lambda x: x['month'])
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
