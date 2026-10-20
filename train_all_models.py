import pandas as pd
import numpy as np
import os
import joblib
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, mean_absolute_error, r2_score

os.makedirs("ml_assets", exist_ok=True)

print("--- [1/5] Loading Data ---")
orders = pd.read_csv("Data/Orders.csv")
users = pd.read_csv("Data/Users.csv")
restaurants = pd.read_csv("Data/Restaurant.csv")

# Clean orders
orders = orders[orders["Sales_amount"] > 0].copy()
orders["order_date"] = pd.to_datetime(orders["order_date"])

# Clean users
users["Occupation"] = users["Occupation"].fillna("Unknown")
users["Age"] = pd.to_numeric(users["Age"], errors="coerce").fillna(users["Age"].median())
users["Gender_Male"] = (users["Gender"].str.lower() == "male").astype(int)

# Reference date for recency calculation
ref_date = orders["order_date"].max()

print("--- [2/5] Preparing User Behavioral Dataset ---")
user_orders = orders.groupby("User_id").agg(
    total_orders=("order_date", "count"),
    total_revenue=("Sales_amount", "sum"),
    last_order_date=("order_date", "max"),
    first_order_date=("order_date", "min")
).reset_index()

user_orders["recency_days"] = (ref_date - user_orders["last_order_date"]).dt.days
user_orders["avg_order_value"] = user_orders["total_revenue"] / user_orders["total_orders"]
user_orders["customer_tenure_days"] = (user_orders["last_order_date"] - user_orders["first_order_date"]).dt.days

# Churn label: inactive for > 90 days
cutoff_date = ref_date - pd.Timedelta(days=90)
user_orders["churn"] = (user_orders["last_order_date"] < cutoff_date).astype(int)

# Merge with user demographics
user_df = user_orders.merge(users[["User_id", "Age", "Gender_Male"]], on="User_id", how="left")
user_df["Age"] = user_df["Age"].fillna(user_df["Age"].median())
user_df["Gender_Male"] = user_df["Gender_Male"].fillna(1).astype(int)

# -------------------------------------------------------------
# 1. Churn Prediction Model (Random Forest Classifier)
# -------------------------------------------------------------
print("--- [3/5] Training Churn Prediction Model ---")
churn_features = ["total_orders", "total_revenue", "avg_order_value", "Age", "Gender_Male"]
X_churn = user_df[churn_features]
y_churn = user_df["churn"]

X_train_c, X_test_c, y_train_c, y_test_c = train_test_split(
    X_churn, y_churn, test_size=0.2, random_state=42, stratify=y_churn
)

rf_churn = RandomForestClassifier(n_estimators=100, max_depth=12, random_state=42, class_weight="balanced", n_jobs=-1)
rf_churn.fit(X_train_c, y_train_c)
prob_c = rf_churn.predict_proba(X_test_c)[:, 1]
churn_auc = roc_auc_score(y_test_c, prob_c)
print(f"Churn Model ROC-AUC: {churn_auc:.4f}")

# Save to ml_assets
joblib.dump(rf_churn, "ml_assets/churn_model.pkl")

# -------------------------------------------------------------
# 2. Customer Lifetime Value (CLTV) Prediction Model
# -------------------------------------------------------------
print("--- [4/5] Training CLTV Regression Model ---")
# Predict total revenue from user behavior and demographics
cltv_features = ["total_orders", "avg_order_value", "recency_days", "Age", "Gender_Male"]
X_cltv = user_df[cltv_features]
# Log-transform target for stability due to skewed revenue distribution
y_cltv = np.log1p(user_df["total_revenue"])

X_train_l, X_test_l, y_train_l, y_test_l = train_test_split(
    X_cltv, y_cltv, test_size=0.2, random_state=42
)

rf_cltv = RandomForestRegressor(n_estimators=80, max_depth=12, random_state=42, n_jobs=-1)
rf_cltv.fit(X_train_l, y_train_l)
pred_l_log = rf_cltv.predict(X_test_l)
pred_l = np.expm1(pred_l_log)
actual_l = np.expm1(y_test_l)

cltv_r2 = r2_score(actual_l, pred_l)
cltv_mae = mean_absolute_error(actual_l, pred_l)
print(f"CLTV Model R^2: {cltv_r2:.4f}, MAE: Rs. {cltv_mae:.2f}")

joblib.dump({
    "model": rf_cltv,
    "features": cltv_features,
    "r2_score": float(cltv_r2),
    "mae": float(cltv_mae),
    "quantiles": {
        "bronze": float(user_df["total_revenue"].quantile(0.25)),
        "silver": float(user_df["total_revenue"].quantile(0.50)),
        "gold": float(user_df["total_revenue"].quantile(0.75)),
        "platinum": float(user_df["total_revenue"].quantile(0.95))
    }
}, "ml_assets/cltv_model.pkl")

# -------------------------------------------------------------
# 3. Customer Segmentation Model (K-Means Clustering)
# -------------------------------------------------------------
print("--- [5/5] Training Customer Segmentation (K-Means) ---")
seg_features = ["recency_days", "total_orders", "total_revenue", "avg_order_value"]
X_seg = user_df[seg_features].copy()

# Log transform skewed features for clean clustering
X_seg_trans = np.log1p(X_seg)
scaler = StandardScaler()
X_seg_scaled = scaler.fit_transform(X_seg_trans)

kmeans = KMeans(n_clusters=4, random_state=42, n_init=10)
user_df["cluster"] = kmeans.fit_predict(X_seg_scaled)

# Characterize clusters
cluster_summary = user_df.groupby("cluster").agg(
    recency_mean=("recency_days", "mean"),
    orders_mean=("total_orders", "mean"),
    revenue_mean=("total_revenue", "mean"),
    aov_mean=("avg_order_value", "mean"),
    count=("User_id", "count")
).reset_index()

cluster_names = {}
# Sort clusters by revenue/orders
ranked_by_rev = cluster_summary.sort_values("revenue_mean", ascending=False)["cluster"].tolist()
cluster_names[ranked_by_rev[0]] = {
    "name": "Champions (High Value Spenders)",
    "badge": "👑 Elite Champions",
    "description": "Top tier customers with high order frequency and top spending.",
    "strategy": "Offer Swiggy One VIP access, exclusive chef previews, and personalized concierge support."
}
cluster_names[ranked_by_rev[1]] = {
    "name": "Loyal Regulars",
    "badge": "⭐ Loyal Foodies",
    "description": "Consistent repeat customers who order regularly and maintain solid AOV.",
    "strategy": "Provide milestone reward points, free delivery passes, and weekend specials."
}
cluster_names[ranked_by_rev[2]] = {
    "name": "Potential Growth (Casual Diners)",
    "badge": "🌱 Casual / Growing",
    "description": "Moderate order frequency with room to increase basket size and regularity.",
    "strategy": "Mid-week discount nudges, combo meal offers, and cuisine recommendations."
}
cluster_names[ranked_by_rev[3]] = {
    "name": "At-Risk / Inactive",
    "badge": "⚠️ At-Risk Inactive",
    "description": "Long recency since last order and low lifetime spend.",
    "strategy": "Aggressive win-back campaigns, 30% discount coupons, and push notifications."
}

joblib.dump({
    "kmeans": kmeans,
    "scaler": scaler,
    "features": seg_features,
    "cluster_names": cluster_names,
    "cluster_summary": cluster_summary.to_dict(orient="records")
}, "ml_assets/segmentation_model.pkl")

# -------------------------------------------------------------
# 4. Recommendation Engine Index
# -------------------------------------------------------------
print("--- Building Recommendation Knowledge Index ---")
rest_clean = restaurants.dropna(subset=["Name", "City", "Cuisine"]).copy()
rest_clean["Rating_num"] = pd.to_numeric(rest_clean["Rating"].replace("--", np.nan), errors="coerce").fillna(3.8)
rest_clean["Rating_count_num"] = rest_clean["Rating_count"].map({"1K+ ratings": 1000, "5K+ ratings": 5000}).fillna(500)

# Extract top performing restaurants across major cities
top_restaurants = (
    rest_clean.sort_values(by=["Rating_num", "Rating_count_num"], ascending=False)
    .groupby(["City", "Cuisine"])
    .head(3)
    .reset_index(drop=True)
)

# Also sample popular dishes per cuisine from Food / Menu if available
sample_dishes = {
    "North Indian": ["Butter Chicken", "Dal Makhani", "Paneer Tikka", "Garlic Naan"],
    "South Indian": ["Masala Dosa", "Idli Vada Combo", "Chettinad Chicken", "Filter Coffee"],
    "Biryani": ["Hyderabadi Chicken Biryani", "Mutton Dum Biryani", "Veg Biryani", "Mirchi Ka Salan"],
    "Chinese": ["Hakka Noodles", "Manchurian Gravy", "Chilli Chicken", "Dim Sums"],
    "Italian": ["Margherita Pizza", "Pasta Alfredo", "Peri Peri Garlic Bread", "Tiramisu"],
    "Fast Food": ["Crispy Chicken Burger", "French Fries", "Cheese Pizza", "Cold Coffee"],
    "Desserts": ["Gulab Jamun", "Chocolate Lava Cake", "Brownie with Ice Cream", "Rasmalai"],
    "Beverages": ["Fresh Mango Shake", "Cold Brew", "Iced Peach Tea", "Lemon Soda"]
}

unique_cities = sorted(rest_clean["City"].dropna().unique().tolist())
for m in ["Bangalore", "Mumbai", "Delhi", "Hyderabad", "Chennai", "Kolkata", "Pune", "Tirupati"]:
    if m not in unique_cities:
        unique_cities.append(m)
unique_cities = sorted(unique_cities)

comprehensive_cuisines = [
    "North Indian", "South Indian", "Chinese", "Biryani", "Fast Food",
    "Bakery", "Italian", "Pizzas", "Burgers", "Desserts", "Ice Cream",
    "American", "Mughlai", "Continental", "Beverages", "Snacks",
    "Street Food", "Chaat", "Tandoor", "Asian", "Arabian", "Bengali",
    "Punjabi", "Thalis", "Healthy Food", "Seafood", "Mexican", "Lebanese",
    "Maharashtrian", "Andhra", "Afghani", "Barbecue", "Pastas", "Sweets", "Cafe",
    "Thai", "Japanese", "Tibetan", "European", "Hyderabadi", "Awadhi",
    "Juices", "Salads", "Kebabs", "Waffles", "Sandwiches", "Rolls", "Shakes",
    "American,Bakery", "Bakery,Italian", "Biryani,North Indian"
]

joblib.dump({
    "top_restaurants": top_restaurants[["Restaurant_id", "Name", "City", "Cuisine", "Rating_num", "Rating_count"]].to_dict(orient="records"),
    "sample_dishes": sample_dishes,
    "cities": unique_cities,
    "all_cities": unique_cities,
    "cuisines": comprehensive_cuisines,
    "all_cuisines": comprehensive_cuisines
}, "ml_assets/recommender_system.pkl")

# -------------------------------------------------------------
# 5. City-Level Demand & Revenue Forecasting Model
# -------------------------------------------------------------
print("--- Building City Demand Forecasting Model ---")
orders["year_month"] = orders["order_date"].dt.to_period("M").astype(str)
city_orders = orders.merge(restaurants[["Restaurant_id", "City"]], on="Restaurant_id", how="inner")

city_monthly = (
    city_orders.groupby(["City", "year_month"])
    .agg(
        monthly_orders=("order_date", "count"),
        monthly_revenue=("Sales_amount", "sum")
    )
    .reset_index()
    .sort_values(by=["City", "year_month"])
)

# Pre-compute historical summaries and simple trend projections for top 10 cities
top_cities = (
    city_orders.groupby("City")["Sales_amount"]
    .sum()
    .sort_values(ascending=False)
    .head(10)
    .index.tolist()
)

city_forecasts = {}
for city in top_cities:
    sub = city_monthly[city_monthly["City"] == city].copy()
    if len(sub) >= 6:
        # compute trend
        recent_orders = sub["monthly_orders"].tail(6).values
        recent_rev = sub["monthly_revenue"].tail(6).values
        avg_order_growth = np.mean(np.diff(recent_orders)) if len(recent_orders) > 1 else 0
        avg_rev_growth = np.mean(np.diff(recent_rev)) if len(recent_rev) > 1 else 0
        
        last_orders = float(recent_orders[-1])
        last_rev = float(recent_rev[-1])
        
        # 3-month forecast
        projected = []
        for m in range(1, 4):
            proj_orders = max(10, int(last_orders + avg_order_growth * m))
            proj_rev = max(50000, float(last_rev + avg_rev_growth * m))
            projected.append({
                "month_offset": f"Month +{m}",
                "forecasted_orders": proj_orders,
                "forecasted_revenue": round(proj_rev, 2)
            })
            
        city_forecasts[city] = {
            "historical_avg_orders": round(float(sub["monthly_orders"].mean()), 1),
            "historical_avg_revenue": round(float(sub["monthly_revenue"].mean()), 2),
            "total_orders": int(sub["monthly_orders"].sum()),
            "total_revenue": round(float(sub["monthly_revenue"].sum()), 2),
            "recent_month_orders": int(last_orders),
            "recent_month_revenue": round(last_rev, 2),
            "projections": projected
        }

joblib.dump({
    "city_forecasts": city_forecasts,
    "top_cities": top_cities
}, "ml_assets/demand_forecaster.pkl")

print("All ML models and assets successfully trained and exported to ml_assets/")
