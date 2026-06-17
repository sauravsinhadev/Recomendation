# 🧠 SynapseRec

### A Real-Time Multi-Channel Hybrid Recommendation Engine

---

## 🚀 Overview

**SynapseRec** is a production-ready, highly sophisticated hybrid recommendation system built using **Python + Flask**. It bridges the gap between simple rule-based engines and complex deep-learning systems.

By leveraging:

* 📐 Vector Space Embeddings
* 📊 Cosine Similarity (Trigonometric Matching)
* 🔗 Jaccard Index (Collaborative Overlap)
* ⏱️ Real-Time Session Decay

SynapseRec delivers **highly personalized, diverse, and context-aware recommendations in real time**.

---

## 🏗️ Architectural Blueprint

SynapseRec follows a **two-stage pipeline** (Retrieval → Ranking), inspired by systems used at Netflix, YouTube, and Google.

```
                  +----------------------------------------------+
                  |              PRODUCT CATALOG                 |
                  +----------------------------------------------+
                                         |
                                         v
+----------------------------------------------------------------------------------+
|                              STAGE 1: RETRIEVAL                                  |
|   (Fetches ~200–300 high-quality candidates from multiple channels)              |
+----------------------------------------------------------------------------------+
  |               |               |               |                 |            |
  v               v               v               v                 v            v
[Trending]   [Profile Cat]   [Profile Tag]   [Session State]   [Search Hist]  [Similar]
  |               |               |               |                 |            |
  +---------------+---------------+---------------+-----------------+------------+
                                         |
                                         v
+----------------------------------------------------------------------------------+
|                               STAGE 2: RANKING                                   |
|   (Scores using cosine similarity & weighted signals)                            |
+----------------------------------------------------------------------------------+
                                         |
                                         v
+----------------------------------------------------------------------------------+
|                             STAGE 3: DIVERSIFICATION                             |
|   (Prevents echo chambers with category caps)                                    |
+----------------------------------------------------------------------------------+
                                         |
                                         v
                             🎯 FINAL USER DASHBOARD
```

---

## ⚡ Core Features

### 🧩 Multi-Dimensional Embeddings

* Converts product metadata (title, tags, description) into vector space
* Enables semantic similarity matching

### 📐 Cosine Similarity Matching

* Measures angle between user preference vectors and product vectors
* Ensures mathematically accurate recommendations

### ⏱️ Real-Time Session Decay

* Tracks short-term intent using recency-based weighting
* Adapts instantly to user behavior

### 🚫 Anti-Echo Chamber System

* Applies category caps per recommendation batch
* Encourages discovery & diversity

### ⚙️ Asynchronous Worker Engine

* Background thread computes heavy operations
* Keeps API responses fast & non-blocking

---

## 📐 The Math Behind SynapseRec

### 1. Cosine Similarity

Measures similarity between vectors:

```
cos(θ) = (A · B) / (||A|| × ||B||)
```

* Higher value → stronger alignment
* Used for content-based filtering

---

### 2. Jaccard Index

Measures overlap between sets:

```
J(A, B) = |A ∩ B| / |A ∪ B|
```

* Used for collaborative filtering
* Compares user interests (tags, categories)

---

## 📂 Project Structure

```
├── app.py                      # Core Flask app + background worker
├── data/
│   ├── users.json              # User data
│   ├── product.json            # Product catalog
│   └── interactions.json       # User behavior logs
├── cache/                      # Auto-generated (worker output)
│   ├── user_profiles.json
│   ├── session_profiles.json
│   ├── similar_products.json
│   ├── similar_users.json
│   ├── category_index.json
│   ├── tag_index.json
│   ├── text_index.json
│   └── recommendations.json
└── templates/                  # Frontend (Tailwind UI)
    ├── index.html
    ├── login.html
    ├── register.html
    └── dashboard.html
```

---

## ⚙️ Setup & Installation

### 1️⃣ Requirements

* Python **3.8+**

---

### 2️⃣ Install Dependencies

```bash
pip install Flask
```

---

### 3️⃣ Run the Server

```bash
python app.py
```

* 🌐 Access: http://localhost:5000
* 🔄 Background worker auto-starts
* ♻️ Cache refresh interval: **60 seconds**

---

## 📊 System Evaluation

Evaluate recommendation quality using built-in metrics:

```python
from app import calculate_system_metrics

score = calculate_system_metrics(user_id=1, k=10)
print(score)
```

---

## 📈 Metrics Explained

### 🎯 Precision @ K

> Out of K recommended items, how many were relevant?

---

### 🔍 Recall

> Out of all relevant items, how many did we successfully recommend?

---

## 🧠 Why SynapseRec?

* ⚡ Real-time personalization
* 🧩 Hybrid (Content + Collaborative)
* 📐 Strong mathematical foundation
* 🚀 Production-ready architecture
* 🛡️ Built-in diversity & bias control

---

## 💡 Future Enhancements

* Deep learning embeddings (BERT / transformers)
* Redis / vector DB integration
* Real-time streaming (Kafka)
* A/B testing framework

---

## 📜 License

MIT License — Free to use, modify, and scale 🚀

---

## 👨‍💻 Author

Built with precision and performance in mind.

---

> ⭐ If you like this project, consider giving it a star!
