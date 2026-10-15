import os
import joblib
import numpy as np
import pandas as pd
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# -------------------------------------------------------------
# Global Model Storage & Lifecycle Management
# -------------------------------------------------------------
ml_models = {}

def load_all_models():
    """Eagerly load all models into global dictionary."""
    try:
        # 1. Churn Model
        if os.path.exists("ml_assets/churn_model.pkl"):
            ml_models["churn"] = joblib.load("ml_assets/churn_model.pkl")
        elif os.path.exists("random_forest_churn.pkl"):
            ml_models["churn"] = joblib.load("random_forest_churn.pkl")
            
        # 2. CLTV Model
        if os.path.exists("ml_assets/cltv_model.pkl"):
            ml_models["cltv"] = joblib.load("ml_assets/cltv_model.pkl")
            
        # 3. Segmentation Model
        if os.path.exists("ml_assets/segmentation_model.pkl"):
            ml_models["segmentation"] = joblib.load("ml_assets/segmentation_model.pkl")
            
        # 4. Recommender System
        if os.path.exists("ml_assets/recommender_system.pkl"):
            ml_models["recommender"] = joblib.load("ml_assets/recommender_system.pkl")
            
        # 5. Demand Forecaster
        if os.path.exists("ml_assets/demand_forecaster.pkl"):
            fc = joblib.load("ml_assets/demand_forecaster.pkl")
            ml_models["forecaster"] = fc
            ml_models["demand_forecaster"] = fc
            
        print("All ML models successfully loaded into memory.")
    except Exception as e:
        print(f"Warning during model loading: {e}")

# Eagerly initialize on import
load_all_models()

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not ml_models:
        load_all_models()
    yield



# -------------------------------------------------------------
# FastAPI App Initialization
# -------------------------------------------------------------
app = FastAPI(
    title="Swiggy Analytics & ML Platform",
    description="Production-grade FastAPI service providing Customer Churn Prediction, CLTV Regression, Customer Segmentation, Food Recommendations, and Demand Forecasting.",
    version="2.0.0",
    lifespan=lifespan
)

# Enable CORS for API consumers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files & Jinja2 Templates
os.makedirs("static", exist_ok=True)
os.makedirs("templates", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("static/swiggy.svg", media_type="image/svg+xml")



# -------------------------------------------------------------
# Pydantic Schemas for REST API
# -------------------------------------------------------------
class ChurnRequest(BaseModel):
    total_orders: float = Field(..., ge=1, description="Total lifetime orders placed by the user")
    total_revenue: float = Field(..., ge=0, description="Total amount spent across all orders (INR)")
    avg_order_value: float = Field(..., ge=0, description="Average order value (INR)")
    age: float = Field(..., ge=10, le=100, description="User age")
    gender: int = Field(..., ge=0, le=1, description="0 = Female, 1 = Male")

class ChurnResponse(BaseModel):
    churn_probability: float
    is_churn_predicted: bool
    risk_level: str
    recommended_action: str

class CLTVRequest(BaseModel):
    total_orders: float = Field(..., ge=1, description="Total orders placed")
    avg_order_value: float = Field(..., ge=1, description="Average order value")
    recency_days: float = Field(..., ge=0, description="Days since last order")
    age: float = Field(25.0, ge=10, le=100)
    gender: int = Field(1, ge=0, le=1)

class CLTVResponse(BaseModel):
    predicted_cltv: float
    cltv_tier: str
    marketing_budget_recommendation: str

class SegmentRequest(BaseModel):
    recency_days: float = Field(..., ge=0)
    total_orders: float = Field(..., ge=1)
    total_revenue: float = Field(..., ge=0)
    avg_order_value: float = Field(..., ge=0)

class SegmentResponse(BaseModel):
    cluster_id: int
    persona_name: str
    badge: str
    description: str
    recommended_strategy: str

class RecommendationRequest(BaseModel):
    city: str = Field("Tirupati", description="City to search")
    cuisine: Optional[str] = Field(None, description="Preferred cuisine")
    limit: int = Field(5, ge=1, le=20)

class ForecastRequest(BaseModel):
    city: str = Field("Tirupati", description="Target city for demand forecast")


# -------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------
def evaluate_churn(total_orders: float, total_revenue: float, avg_order_value: float, age: float, gender: float):
    model = ml_models.get("churn")
    if model is None:
        raise HTTPException(status_code=500, detail="Churn model not loaded.")
    
    cols = ["total_orders", "total_revenue", "avg_order_value", "Age", "Gender_Male"]
    features = pd.DataFrame([[total_orders, total_revenue, avg_order_value, age, gender]], columns=cols)
    prob = model.predict_proba(features)[0][1]
    prob_percent = round(float(prob) * 100, 2)
    is_churn = bool(prob_percent >= 50.0)

    if prob_percent >= 70:
        risk_level = "High Risk 🔴"
        action = """1. Offer instant 30% discount coupon on preferred cuisine.
2. Send immediate retention push notification.
3. Provide free delivery pass for next 3 orders.
4. Credit 250 loyalty bonus points expiring in 7 days."""
    elif prob_percent >= 40:
        risk_level = "Medium Risk 🟠"
        action = """1. Deploy personalized 15% discount campaign.
2. Recommend top-rated restaurants in customer's area.
3. Highlight trending weekend chef specials.
4. Send timely lunch/dinner reminder notifications."""
    else:
        risk_level = "Low Risk 🟢"
        action = """1. Maintain engagement with milestone reward points.
2. Upsell Swiggy One premium membership.
3. Offer referral bonus for inviting colleagues/friends.
4. Provide VIP priority customer support."""

    return prob_percent, is_churn, risk_level, action


# -------------------------------------------------------------
# HTML Web Routes
# -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    recommender = ml_models.get("recommender", {})
    forecaster = ml_models.get("forecaster", {})
    
    cities = recommender.get("cities", ["Tirupati", "Sirsi", "Bangalore", "Kovilpatti", "Chennai"])
    cuisines = recommender.get("cuisines", ["North Indian", "South Indian", "Biryani", "Chinese", "Italian", "Fast Food"])
    top_cities = forecaster.get("top_cities", ["Tirupati", "Sirsi", "Bangalore", "Kovilpatti"])
    
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "cities": cities,
            "cuisines": cuisines,
            "top_cities": top_cities
        }
    )


@app.post("/predict", response_class=HTMLResponse)
async def predict_form(
    request: Request,
    total_orders: float = Form(...),
    total_revenue: float = Form(...),
    avg_order_value: float = Form(...),
    age: float = Form(...),
    gender: float = Form(...)
):
    try:
        prob_percent, _, risk_level, recommended_action = evaluate_churn(
            total_orders, total_revenue, avg_order_value, age, gender
        )
        return templates.TemplateResponse(
            request=request,
            name="result.html",
            context={
                "probability": prob_percent,
                "risk_level": risk_level,
                "recommended_action": recommended_action
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            request=request,
            name="result.html",
            context={
                "probability": "Error",
                "risk_level": "Error",
                "recommended_action": str(e)
            }
        )


# -------------------------------------------------------------
# REST API Endpoints
# -------------------------------------------------------------
@app.post("/api/churn/predict", response_model=ChurnResponse, tags=["ML Models"])
async def api_predict_churn(data: ChurnRequest):
    """Predicts customer churn probability and returns prescriptive retention recommendations."""
    prob_percent, is_churn, risk_level, action = evaluate_churn(
        data.total_orders, data.total_revenue, data.avg_order_value, data.age, data.gender
    )
    return ChurnResponse(
        churn_probability=prob_percent,
        is_churn_predicted=is_churn,
        risk_level=risk_level,
        recommended_action=action
    )


@app.post("/api/cltv/predict", response_model=CLTVResponse, tags=["ML Models"])
async def api_predict_cltv(data: CLTVRequest):
    """Predicts Customer Lifetime Value (CLTV) in INR and assigns a customer value tier."""
    cltv_pack = ml_models.get("cltv")
    if not cltv_pack:
        raise HTTPException(status_code=500, detail="CLTV model not available.")
    
    model = cltv_pack["model"]
    cols = cltv_pack.get("features", ["total_orders", "avg_order_value", "recency_days", "Age", "Gender_Male"])
    features = pd.DataFrame([[data.total_orders, data.avg_order_value, data.recency_days, data.age, data.gender]], columns=cols)
    pred_log = model.predict(features)[0]
    predicted_val = round(float(np.expm1(pred_log)), 2)

    # Classify tier
    q = cltv_pack.get("quantiles", {})
    if predicted_val >= q.get("platinum", 35000):
        tier = "🏆 Platinum VIP Customer"
        cac_rec = "Allocate up to ₹1,500 CAC. Offer exclusive concierge service and personal Swiggy Black perks."
    elif predicted_val >= q.get("gold", 15000):
        tier = "🥇 Gold High-Value Customer"
        cac_rec = "Allocate up to ₹800 CAC. Offer annual Swiggy One membership discount and VIP lounge passes."
    elif predicted_val >= q.get("silver", 5000):
        tier = "🥈 Silver Regular Customer"
        cac_rec = "Allocate up to ₹300 CAC. Focus on basket size expansion through combo coupons."
    else:
        tier = "🥉 Bronze Entry Customer"
        cac_rec = "Allocate up to ₹100 CAC. Focus on repeat order triggers and free delivery."

    return CLTVResponse(
        predicted_cltv=predicted_val,
        cltv_tier=tier,
        marketing_budget_recommendation=cac_rec
    )


@app.post("/api/segment/predict", response_model=SegmentResponse, tags=["ML Models"])
async def api_segment_customer(data: SegmentRequest):
    """Assigns customer into an unsupervised K-Means behavioral persona cluster."""
    seg_pack = ml_models.get("segmentation")
    if not seg_pack:
        raise HTTPException(status_code=500, detail="Segmentation model not available.")
    
    kmeans = seg_pack["kmeans"]
    scaler = seg_pack["scaler"]
    cluster_names = seg_pack["cluster_names"]
    cols = seg_pack.get("features", ["recency_days", "total_orders", "total_revenue", "avg_order_value"])

    raw = pd.DataFrame([[data.recency_days, data.total_orders, data.total_revenue, data.avg_order_value]], columns=cols)
    log_trans = np.log1p(raw)
    scaled = scaler.transform(log_trans)
    cluster_id = int(kmeans.predict(scaled)[0])

    cluster_info = cluster_names.get(cluster_id, {
        "name": f"Segment #{cluster_id}",
        "badge": "Standard Segment",
        "description": "Standard behavioral profile.",
        "strategy": "Standard retention & engagement campaigns."
    })

    return SegmentResponse(
        cluster_id=cluster_id,
        persona_name=cluster_info["name"],
        badge=cluster_info["badge"],
        description=cluster_info["description"],
        recommended_strategy=cluster_info["strategy"]
    )


@app.post("/api/recommend", tags=["ML Models"])
async def api_recommend_restaurants(data: RecommendationRequest):
    """Recommends top restaurants and signature dishes based on city, cuisine, and rating weights."""
    rec_pack = ml_models.get("recommender")
    if not rec_pack:
        raise HTTPException(status_code=500, detail="Recommendation engine not available.")
    
    top_rest = rec_pack.get("top_restaurants", [])
    sample_dishes = rec_pack.get("sample_dishes", {})

    city_filter = [r for r in top_rest if r.get("City", "").lower() == data.city.lower()]
    if not city_filter:
        city_filter = top_rest

    if data.cuisine:
        cuisine_filter = [r for r in city_filter if data.cuisine.lower() in str(r.get("Cuisine", "")).lower()]
        if cuisine_filter:
            city_filter = cuisine_filter

    results = city_filter[:data.limit]
    
    # Attach signature dishes
    enriched = []
    for r in results:
        matched_cuisine = r.get("Cuisine", "North Indian")
        dishes = sample_dishes.get(matched_cuisine, ["Signature Biryani", "Special Platter", "Chef Special Dish"])
        enriched.append({
            "name": r.get("Name"),
            "city": r.get("City"),
            "cuisine": r.get("Cuisine"),
            "rating": r.get("Rating_num", 4.0),
            "rating_count": r.get("Rating_count", "1K+ ratings"),
            "recommended_dishes": dishes[:3]
        })

    return {
        "query": {"city": data.city, "cuisine": data.cuisine},
        "count": len(enriched),
        "recommendations": enriched
    }


@app.post("/api/forecast/predict", tags=["ML Models"])
async def api_forecast_demand(data: ForecastRequest):
    """Returns 3-month projected order volume and sales revenue forecast for the requested city."""
    forecaster = ml_models.get("demand_forecaster")
    if not forecaster:
        raise HTTPException(status_code=500, detail="Demand forecaster not available.")
    
    city_forecasts = forecaster.get("city_forecasts", {})
    forecast_data = city_forecasts.get(data.city)

    if not forecast_data:
        # Fallback to closest top city
        default_city = list(city_forecasts.keys())[0]
        forecast_data = city_forecasts[default_city]
        matched_city = default_city
    else:
        matched_city = data.city

    return {
        "city": matched_city,
        "historical_avg_monthly_orders": forecast_data["historical_avg_orders"],
        "historical_avg_monthly_revenue": forecast_data["historical_avg_revenue"],
        "recent_month_orders": forecast_data["recent_month_orders"],
        "recent_month_revenue": forecast_data["recent_month_revenue"],
        "projections": forecast_data["projections"]
    }


@app.get("/api/stats", tags=["Metadata & KPIs"])
async def api_stats():
    """Returns summary analytics KPIs from the Swiggy dataset."""
    return {
        "total_revenue": "₹963,829,620",
        "total_orders": 148575,
        "average_order_value": "₹6,487.16",
        "active_users": 9457,
        "churned_users": 67778,
        "baseline_churn_rate": "87.76%",
        "repeat_users": 43882,
        "one_time_users": 33691,
        "top_performing_market": "Tirupati",
        "top_brand_partner": "Domino's Pizza"
    }


# -------------------------------------------------------------
# Local Development Execution
# -------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)