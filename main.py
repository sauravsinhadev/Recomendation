import json
import math
import os
import re
import time
from collections import defaultdict
from datetime import datetime
from threading import Thread

from flask import Flask, jsonify, redirect, render_template, request, session

app = Flask(__name__)
app.secret_key = "mysecretkey"

DATA_DIR = "data"
CACHE_DIR = "cache"

USERS_FILE = os.path.join(DATA_DIR, "users.json")
PRODUCTS_FILE = os.path.join(DATA_DIR, "product.json")
INTERACTIONS_FILE = os.path.join(DATA_DIR, "interactions.json")
SEARCH_HISTORY_FILE = os.path.join(CACHE_DIR, "search_history.json")

ACTION_WEIGHTS = {
    "view": 1,
    "like": 5,
    "save": 10,
}

worker_started = False


# --------------------------
# JSON HELPERS
# --------------------------

def ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def plainify(value):
    if isinstance(value, dict):
        return {str(k): plainify(v) for k, v in value.items()}
    if isinstance(value, list):
        return [plainify(v) for v in value]
    if isinstance(value, set):
        return [plainify(v) for v in value]
    return value


def load_json(filepath, default=None):
    if default is None:
        default = {}
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(filepath, data):
    ensure_parent_dir(filepath)
    tmp_path = filepath + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(plainify(data), f, indent=4, ensure_ascii=False)
    os.replace(tmp_path, filepath)


def load_users():
    return load_json(USERS_FILE, [])


def save_users(users):
    save_json(USERS_FILE, users)


def load_products():
    return load_json(PRODUCTS_FILE, [])


def save_products(products):
    save_json(PRODUCTS_FILE, products)


def load_interactions():
    return load_json(INTERACTIONS_FILE, [])


def save_interactions(interactions):
    save_json(INTERACTIONS_FILE, interactions)


# --------------------------
# SMALL UTILITIES
# --------------------------

def tokenize(text):
    if not text:
        return []
    return re.findall(r"[a-z0-9]+", str(text).lower())


def parse_date(date_str):
    try:
        return datetime.strptime(str(date_str), "%Y-%m-%d")
    except Exception:
        return datetime(1970, 1, 1)


def product_tokens(product):
    text = " ".join([
        str(product.get("title", "")),
        str(product.get("description", "")),
        str(product.get("category", "")),
        " ".join(product.get("hashtags", []) or []),
    ])
    return set(tokenize(text))


def top_keys(score_dict, n=5):
    return [
        k for k, _ in sorted(
            score_dict.items(),
            key=lambda x: x[1],
            reverse=True
        )[:n]
    ]


def cosine_dict(a, b):
    if not a or not b:
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    keys = set(a.keys()) | set(b.keys())
    for k in keys:
        av = float(a.get(k, 0))
        bv = float(b.get(k, 0))
        dot += av * bv
        norm_a += av * av
        norm_b += bv * bv
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))


def jaccard(a, b):
    a = set(a)
    b = set(b)
    if not a and not b:
        return 0.0
    return len(a & b) / max(1, len(a | b))


def add_weighted_vector(target, source, weight):
    if not source:
        return
    for k, v in source.items():
        target[k] = float(target.get(k, 0)) + (float(v) * float(weight))


def freshness_score(product):
    dt = parse_date(product.get("created_at", "1970-01-01"))
    age_days = max(0, (datetime.utcnow() - dt).days)
    return max(0.0, 60.0 - (age_days * 1.5))


def popularity_score(product):
    return (
        int(product.get("liked", 0) or 0) * 2 +
        int(product.get("saved", 0) or 0) * 4
    )


def product_by_id_map(products):
    return {int(p["id"]): p for p in products}


def top_ids_from_score_map(score_map, limit=200):
    items = sorted(
        score_map.items(),
        key=lambda x: x[1],
        reverse=True
    )
    return [int(pid) for pid, _ in items[:limit]]


# --------------------------
# USER HELPERS
# --------------------------

def my_liked(user_id):
    interactions = load_interactions()
    products = load_products()
    liked_ids = {
        int(i["product_id"])
        for i in interactions
        if int(i["user_id"]) == int(user_id) and i["action"] == "like"
    }
    return [p for p in products if int(p["id"]) in liked_ids]


def my_saved(user_id):
    interactions = load_interactions()
    products = load_products()
    saved_ids = {
        int(i["product_id"])
        for i in interactions
        if int(i["user_id"]) == int(user_id) and i["action"] == "save"
    }
    return [p for p in products if int(p["id"]) in saved_ids]


def record_search(user_id, query):
    if not user_id:
        return
    query = (query or "").strip()
    if not query:
        return

    history = load_json(SEARCH_HISTORY_FILE, {})
    uid = str(user_id)
    history.setdefault(uid, [])
    history[uid].append({
        "query": query,
        "ts": time.time()
    })
    history[uid] = history[uid][-30:]
    save_json(SEARCH_HISTORY_FILE, history)


# --------------------------
# BUILD INDEXES / EMBEDDINGS
# --------------------------

def build_catalog_indexes():
    products = load_products()
    sorted_products = sorted(
        products,
        key=lambda p: (
            parse_date(p.get("created_at", "1970-01-01")),
            int(p.get("id", 0))
        ),
        reverse=True
    )

    category_index = defaultdict(list)
    tag_index = defaultdict(list)
    text_index = defaultdict(list)

    for p in sorted_products:
        pid = int(p["id"])
        category = str(p.get("category", "Other"))
        category_index[category].append(pid)

        tags = [str(t).lower() for t in (p.get("hashtags", []) or [])]
        tokens = product_tokens(p)

        for tag in tags:
            tag_index[tag].append(pid)

        for token in tokens:
            text_index[token].append(pid)

    save_json(os.path.join(CACHE_DIR, "category_index.json"), category_index)
    save_json(os.path.join(CACHE_DIR, "tag_index.json"), tag_index)
    save_json(os.path.join(CACHE_DIR, "text_index.json"), text_index)


def build_product_embeddings():
    products = load_products()
    embeddings = {}

    for p in products:
        vec = defaultdict(float)

        cat = str(p.get("category", "")).lower().strip()
        if cat:
            vec[cat] += 3.0

        for tag in (p.get("hashtags", []) or []):
            token = str(tag).lower().strip()
            if token:
                vec[token] += 2.0

        for word in tokenize(p.get("title", "")):
            vec[word] += 1.4

        for word in tokenize(p.get("description", ""))[:20]:
            vec[word] += 0.4

        embeddings[str(int(p["id"]))] = dict(vec)

    save_json(os.path.join(CACHE_DIR, "product_embeddings.json"), embeddings)


def build_user_profiles():
    products = load_products()
    interactions = load_interactions()
    product_map = product_by_id_map(products)
    product_embeddings = load_json(os.path.join(CACHE_DIR, "product_embeddings.json"), {})

    profiles = {}

    for i in interactions:
        uid = str(int(i["user_id"]))
        pid = int(i["product_id"])
        product = product_map.get(pid)
        if not product:
            continue

        weight = ACTION_WEIGHTS.get(i["action"], 1)

        if uid not in profiles:
            profiles[uid] = {
                "categories": {},
                "hashtags": {},
                "embedding": {}
            }

        category = str(product.get("category", "Other"))
        profiles[uid]["categories"][category] = (
            float(profiles[uid]["categories"].get(category, 0)) + weight
        )

        for tag in (product.get("hashtags", []) or []):
            tag = str(tag).lower()
            profiles[uid]["hashtags"][tag] = (
                float(profiles[uid]["hashtags"].get(tag, 0)) + weight
            )

        add_weighted_vector(
            profiles[uid]["embedding"],
            product_embeddings.get(str(pid), {}),
            weight
        )

    save_json(os.path.join(CACHE_DIR, "user_profiles.json"), profiles)


def build_session_profiles():
    products = load_products()
    interactions = load_interactions()
    product_map = product_by_id_map(products)
    product_embeddings = load_json(os.path.join(CACHE_DIR, "product_embeddings.json"), {})

    recent_by_user = defaultdict(list)
    for item in interactions:
        recent_by_user[str(int(item["user_id"]))].append(item)

    sessions = {}

    for uid, items in recent_by_user.items():
        items = items[-15:]
        session_profile = {
            "categories": {},
            "hashtags": {},
            "embedding": {}
        }

        for offset, item in enumerate(reversed(items)):
            pid = int(item["product_id"])
            product = product_map.get(pid)
            if not product:
                continue

            base_weight = ACTION_WEIGHTS.get(item["action"], 1)
            recency_weight = 1.0 + (offset * 0.18)
            weight = base_weight * recency_weight

            category = str(product.get("category", "Other"))
            session_profile["categories"][category] = (
                float(session_profile["categories"].get(category, 0)) + weight
            )

            for tag in (product.get("hashtags", []) or []):
                tag = str(tag).lower()
                session_profile["hashtags"][tag] = (
                    float(session_profile["hashtags"].get(tag, 0)) + weight
                )

            add_weighted_vector(
                session_profile["embedding"],
                product_embeddings.get(str(pid), {}),
                weight
            )

        sessions[uid] = session_profile

    save_json(os.path.join(CACHE_DIR, "session_profiles.json"), sessions)


def build_trending():
    products = load_products()
    interactions = load_interactions()

    trending = defaultdict(float)

    for item in interactions:
        pid = str(int(item["product_id"]))
        trending[pid] += ACTION_WEIGHTS.get(item["action"], 1)

    for p in products:
        pid = str(int(p["id"]))
        trending[pid] += math.log1p(popularity_score(p)) * 2
        trending[pid] += freshness_score(p) * 0.15

    save_json(os.path.join(CACHE_DIR, "trending.json"), trending)


def build_similar_products():
    products = load_products()
    product_map = product_by_id_map(products)
    product_embeddings = load_json(os.path.join(CACHE_DIR, "product_embeddings.json"), {})
    category_index = load_json(os.path.join(CACHE_DIR, "category_index.json"), {})
    tag_index = load_json(os.path.join(CACHE_DIR, "tag_index.json"), {})

    similar = {}

    for p in products:
        pid = int(p["id"])
        category = str(p.get("category", "Other"))
        tags = [str(t).lower() for t in (p.get("hashtags", []) or [])]
        p_tokens = product_tokens(p)
        p_vec = product_embeddings.get(str(pid), {})

        candidate_ids = set(category_index.get(category, [])[:250])
        for tag in tags:
            candidate_ids.update(tag_index.get(tag, [])[:120])

        candidate_ids.discard(pid)

        scored = []
        for cid in candidate_ids:
            other = product_map.get(int(cid))
            if not other:
                continue

            score = 0.0
            if str(other.get("category", "Other")) == category:
                score += 40

            other_tags = [str(t).lower() for t in (other.get("hashtags", []) or [])]
            common_tags = len(set(tags) & set(other_tags))
            score += common_tags * 18

            score += len(p_tokens & product_tokens(other)) * 4
            score += cosine_dict(p_vec, product_embeddings.get(str(int(other["id"])), {})) * 25

            price_a = float(p.get("price", 0) or 0)
            price_b = float(other.get("price", 0) or 0)
            if price_a > 0:
                price_diff_ratio = abs(price_a - price_b) / price_a
                score += max(0.0, 12.0 - (price_diff_ratio * 12.0))

            score += freshness_score(other) * 0.2

            if score > 0:
                scored.append({
                    "id": int(other["id"]),
                    "score": round(score, 3)
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        similar[str(pid)] = scored[:10]

    save_json(os.path.join(CACHE_DIR, "similar_products.json"), similar)


def build_similar_users():
    profiles = load_json(os.path.join(CACHE_DIR, "user_profiles.json"), {})
    similar = {}

    if not profiles:
        save_json(os.path.join(CACHE_DIR, "similar_users.json"), {})
        return

    category_index = defaultdict(set)
    tag_index = defaultdict(set)

    for uid, profile in profiles.items():
        for cat in (profile.get("categories", {}) or {}).keys():
            category_index[cat].add(uid)
        for tag in (profile.get("hashtags", {}) or {}).keys():
            tag_index[tag].add(uid)

    for uid, profile in profiles.items():
        base_vec = profile.get("embedding", {}) or {}
        base_cats = set((profile.get("categories", {}) or {}).keys())
        base_tags = set((profile.get("hashtags", {}) or {}).keys())

        candidate_uids = set()
        for cat in top_keys(profile.get("categories", {}), 5):
            candidate_uids |= category_index.get(cat, set())
        for tag in top_keys(profile.get("hashtags", {}), 12):
            candidate_uids |= tag_index.get(tag, set())

        candidate_uids.discard(uid)

        scored = []
        for other_uid in list(candidate_uids)[:300]:
            other = profiles.get(other_uid)
            if not other:
                continue

            other_vec = other.get("embedding", {}) or {}
            other_cats = set((other.get("categories", {}) or {}).keys())
            other_tags = set((other.get("hashtags", {}) or {}).keys())

            score = 0.0
            score += cosine_dict(base_vec, other_vec) * 100
            score += jaccard(base_cats, other_cats) * 20
            score += jaccard(base_tags, other_tags) * 15

            if score > 0:
                scored.append({
                    "id": int(other_uid),
                    "score": round(score, 3)
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        similar[uid] = scored[:10]

    save_json(os.path.join(CACHE_DIR, "similar_users.json"), similar)


# --------------------------
# RECOMMENDATION ENGINE
# --------------------------

def build_candidate_pool(uid, profile, session_profile, trending, category_index, tag_index, text_index, similar_products, similar_users, search_history, positive_items_by_user):
    candidates = set()

    # Trending and latest style exploration
    candidates.update(top_ids_from_score_map(trending, 250))

    # Category and hashtag matches
    for cat in top_keys(profile.get("categories", {}), 5):
        candidates.update(category_index.get(cat, [])[:150])

    for tag in top_keys(profile.get("hashtags", {}), 12):
        candidates.update(tag_index.get(tag, [])[:120])

    # Session engine
    for cat in top_keys(session_profile.get("categories", {}), 4):
        candidates.update(category_index.get(cat, [])[:120])

    for tag in top_keys(session_profile.get("hashtags", {}), 10):
        candidates.update(tag_index.get(tag, [])[:100])

    # Search history engine
    for q in (search_history.get(uid, []) or [])[-10:]:
        for token in tokenize(q.get("query", "")):
            candidates.update(text_index.get(token, [])[:60])

    # Similar products engine
    for seed_pid in positive_items_by_user.get(uid, set()):
        for item in (similar_products.get(str(seed_pid), []) or [])[:8]:
            candidates.add(int(item["id"]))

    # Similar users engine
    for item in (similar_users.get(uid, []) or [])[:8]:
        other_uid = str(int(item["id"]))
        for pid in positive_items_by_user.get(other_uid, set()):
            candidates.add(int(pid))

    return candidates


def rerank_diverse(ranked_items, limit=24, max_per_category=3):
    final_items = []
    seen_ids = set()
    category_count = defaultdict(int)

    for item in ranked_items:
        pid = int(item["id"])
        cat = str(item.get("category", "Other"))

        if pid in seen_ids:
            continue

        if category_count[cat] >= max_per_category:
            continue

        final_items.append(item)
        seen_ids.add(pid)
        category_count[cat] += 1

        if len(final_items) >= limit:
            return final_items

    for item in ranked_items:
        pid = int(item["id"])
        if pid in seen_ids:
            continue
        final_items.append(item)
        seen_ids.add(pid)
        if len(final_items) >= limit:
            break

    return final_items


def build_recommendations():
    products = load_products()
    product_map = product_by_id_map(products)

    profiles = load_json(os.path.join(CACHE_DIR, "user_profiles.json"), {})
    session_profiles = load_json(os.path.join(CACHE_DIR, "session_profiles.json"), {})
    trending = load_json(os.path.join(CACHE_DIR, "trending.json"), {})
    similar_products = load_json(os.path.join(CACHE_DIR, "similar_products.json"), {})
    similar_users = load_json(os.path.join(CACHE_DIR, "similar_users.json"), {})
    category_index = load_json(os.path.join(CACHE_DIR, "category_index.json"), {})
    tag_index = load_json(os.path.join(CACHE_DIR, "tag_index.json"), {})
    text_index = load_json(os.path.join(CACHE_DIR, "text_index.json"), {})
    search_history = load_json(SEARCH_HISTORY_FILE, {})
    product_embeddings = load_json(os.path.join(CACHE_DIR, "product_embeddings.json"), {})

    interactions = load_interactions()
    positive_items_by_user = defaultdict(set)
    seen_items_by_user = defaultdict(set)

    for item in interactions:
        uid = str(int(item["user_id"]))
        pid = int(item["product_id"])
        seen_items_by_user[uid].add(pid)
        if item["action"] in ("like", "save"):
            positive_items_by_user[uid].add(pid)

    recommendations = {}

    for uid, profile in profiles.items():
        session_profile = session_profiles.get(uid, {
            "categories": {},
            "hashtags": {},
            "embedding": {}
        })

        candidates = build_candidate_pool(
            uid,
            profile,
            session_profile,
            trending,
            category_index,
            tag_index,
            text_index,
            similar_products,
            similar_users,
            search_history,
            positive_items_by_user
        )

        # Search history tokens used as a direct boost
        recent_queries = [x.get("query", "") for x in (search_history.get(uid, []) or [])[-10:]]
        recent_tokens = set(tokenize(" ".join(recent_queries)))

        # Boost maps
        similar_product_boost = defaultdict(float)
        for seed_pid in positive_items_by_user.get(uid, set()):
            for rank, rec in enumerate((similar_products.get(str(seed_pid), []) or [])[:8]):
                similar_product_boost[int(rec["id"])] += max(0.0, float(rec.get("score", 0))) * 0.25

        similar_user_boost = defaultdict(float)
        for rec in (similar_users.get(uid, []) or [])[:8]:
            other_uid = str(int(rec["id"]))
            sim_score = float(rec.get("score", 0))
            for pid in positive_items_by_user.get(other_uid, set()):
                similar_user_boost[int(pid)] += sim_score * 0.35

        search_boost = defaultdict(float)
        for token in recent_tokens:
            for pid in text_index.get(token, [])[:80]:
                search_boost[int(pid)] += 12.0

        user_vec = profile.get("embedding", {}) or {}
        session_vec = session_profile.get("embedding", {}) or {}

        scored_items = []
        for pid in candidates:
            product = product_map.get(int(pid))
            if not product:
                continue

            if int(pid) in seen_items_by_user.get(uid, set()):
                continue

            category = str(product.get("category", "Other"))
            tags = [str(t).lower() for t in (product.get("hashtags", []) or [])]

            score = 0.0
            score += math.log1p(float(trending.get(str(pid), 0) or 0)) * 12.0
            score += float(profile.get("categories", {}).get(category, 0) or 0) * 2.0
            score += sum(float(profile.get("hashtags", {}).get(tag, 0) or 0) for tag in tags) * 1.2
            score += float(session_profile.get("categories", {}).get(category, 0) or 0) * 2.4
            score += sum(float(session_profile.get("hashtags", {}).get(tag, 0) or 0) for tag in tags) * 1.5

            # Embedding score from user profile and current session
            p_vec = product_embeddings.get(str(pid), {})
            score += cosine_dict(user_vec, p_vec) * 55.0
            score += cosine_dict(session_vec, p_vec) * 35.0

            # Recommendation boosts from other engines
            score += similar_product_boost[int(pid)]
            score += similar_user_boost[int(pid)]
            score += search_boost[int(pid)]

            # Freshness / popularity
            score += freshness_score(product) * 0.8
            score += math.log1p(popularity_score(product)) * 1.7

            scored_items.append({
                "id": int(pid),
                "score": round(score, 3),
                "category": category
            })

        scored_items.sort(key=lambda x: x["score"], reverse=True)
        final_items = rerank_diverse(scored_items, limit=30, max_per_category=3)
        recommendations[uid] = final_items

    save_json(os.path.join(CACHE_DIR, "recommendations.json"), recommendations)


def build_all():
    build_catalog_indexes()
    build_product_embeddings()
    build_user_profiles()
    build_session_profiles()
    build_trending()
    build_similar_products()
    build_similar_users()
    build_recommendations()


def recommendation_worker():
    while True:
        try:
            build_all()
            print("[Worker] caches refreshed")
        except Exception as e:
            print(f"[Worker Error] {e}")
        time.sleep(60)


def start_worker():
    global worker_started
    if worker_started:
        return
    worker_started = True
    thread = Thread(target=recommendation_worker, daemon=True)
    thread.start()


# --------------------------
# ROUTES
# --------------------------

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        users = load_users()

        for user in users:
            if user["username"] == username and user["password"] == password:
                session["user_id"] = int(user["id"])
                session["username"] = user["username"]
                return redirect("/dashboard")

        return "Invalid username or password"

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        users = load_users()

        new_user = {
            "id": len(users) + 1,
            "username": request.form["username"],
            "password": request.form["password"],
            "age": request.form["age"],
            "gender": request.form["gender"],
            "location": request.form["location"],
        }

        users.append(new_user)
        save_users(users)
        return redirect("/login")

    return render_template("register.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")

    user_id = int(session["user_id"])
    products = load_products()
    product_map = product_by_id_map(products)
    interactions = load_interactions()

    latest = sorted(
        products,
        key=lambda x: (
            parse_date(x.get("created_at", "1970-01-01")),
            int(x.get("id", 0))
        ),
        reverse=True
    )[:10]

    view_count = defaultdict(int)
    like_count = defaultdict(int)

    for i in interactions:
        pid = int(i["product_id"])
        if i["action"] == "view":
            view_count[pid] += 1
        if i["action"] == "like":
            like_count[pid] += 1

    most_viewed = sorted(
        products,
        key=lambda x: view_count.get(int(x["id"]), 0),
        reverse=True
    )[:10]

    most_liked = sorted(
        products,
        key=lambda x: like_count.get(int(x["id"]), 0),
        reverse=True
    )[:10]

    recommendations_cache = load_json(os.path.join(CACHE_DIR, "recommendations.json"), {})
    user_recommendations = recommendations_cache.get(str(user_id), [])

    recommended = []
    for item in user_recommendations[:12]:
        pid = int(item["id"])
        product = product_map.get(pid)
        if product:
            row = dict(product)
            row["score"] = item.get("score", 0)
            recommended.append(row)

    return render_template(
        "dashboard.html",
        username=session["username"],
        latest=latest,
        most_viewed=most_viewed,
        most_liked=most_liked,
        recommended=recommended,
        my_liked=my_liked(user_id),
        my_saved=my_saved(user_id),
    )


@app.route("/api/search")
def search_api():
    q = (request.args.get("q", "") or "").strip().lower()
    products = load_products()

    if not q:
        return jsonify([])

    if "user_id" in session:
        record_search(int(session["user_id"]), q)

    results = []
    tokens = tokenize(q)

    for p in products:
        title = str(p.get("title", "")).lower()
        desc = str(p.get("description", "")).lower()
        cat = str(p.get("category", "")).lower()
        tags = [str(t).lower() for t in (p.get("hashtags", []) or [])]

        score = 0.0
        if q in title:
            score += 60
        if q in cat:
            score += 45
        if q in desc:
            score += 18

        for tag in tags:
            if q == tag:
                score += 28
            elif q in tag:
                score += 12

        title_tokens = set(tokenize(title))
        desc_tokens = set(tokenize(desc))
        tag_tokens = set(tags)

        overlap = len(set(tokens) & (title_tokens | desc_tokens | tag_tokens))
        score += overlap * 9

        score += math.log1p(popularity_score(p)) * 1.2
        score += freshness_score(p) * 0.12

        if score > 0:
            item = dict(p)
            item["score"] = round(score, 2)
            results.append(item)

    results.sort(key=lambda x: x["score"], reverse=True)
    return jsonify(results[:40])


@app.route("/api/action")
def action():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    action_type = request.args.get("action", "")
    pid = int(request.args.get("pid", 0))
    user_id = int(session["user_id"])

    if action_type not in ("like", "save"):
        return jsonify({"error": "Invalid action"}), 400

    interactions = load_interactions()
    products = load_products()
    target_product = next((p for p in products if int(p["id"]) == pid), None)

    found = False
    for item in interactions[:]:
        if (
            int(item["user_id"]) == user_id and
            int(item["product_id"]) == pid and
            item["action"] == action_type
        ):
            interactions.remove(item)
            found = True

            if target_product:
                field = "liked" if action_type == "like" else "saved"
                current = int(target_product.get(field, 0) or 0)
                target_product[field] = max(0, current - 1)
            break

    if not found:
        interactions.append({
            "user_id": user_id,
            "product_id": pid,
            "action": action_type
        })

        if target_product:
            field = "liked" if action_type == "like" else "saved"
            current = int(target_product.get(field, 0) or 0)
            target_product[field] = current + 1

    save_interactions(interactions)
    save_products(products)

    return redirect("/dashboard")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


if __name__ == "__main__":
    build_all()
    start_worker()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)