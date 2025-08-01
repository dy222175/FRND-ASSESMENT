# Backend Engineer Assignment Solution
## 🚀 Key Features

* **Data Ingestion**: Upload JSON files through a dedicated API endpoint. The uploaded data is normalized and stored in a SQLite database.
* **REST API**:

  * Retrieve all songs with pagination, sorted by rating.
  * Search songs by title.
  * Rate a song (1 to 5 stars).
* **Caching**: Integrates Redis to cache frequently accessed data like the list of songs.
* **Deployment**: Fully containerized using Docker and orchestrated with Docker Compose for ease of deployment.

---

## 🛠 Getting Started

### Step 1: Clone the Repository

```bash
git clone https://github.com/dy222175/FRND-ASSESMENT.git
cd FRND-ASSESMENT
```

### Step 2: Using SQLite

SQLite is used as the default database for quick setup. No separate configuration is required—SQLite creates a database file automatically after running migrations.

---

## ⚙️ Set Up the Python Environment

### Step 3: Create and Activate a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 4: Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 5: Run Database Migrations

For a fresh start, you can delete old migrations (optional):

```bash
rm api/migrations/0*.py
```

Then create and apply new migrations:

```bash
python manage.py makemigrations api
python manage.py migrate
```

---

## 🧪 How to Use the API

### Step 1: Start the Development Server

```bash
python manage.py runserver
```

The API will be available at:

* `http://localhost:8000`
* or `http://127.0.0.1:8000`

---

### Step 2: Upload JSON Data

Use tools like **Postman** or **cURL** to make a POST request.

**Endpoint:**

```
POST /api/songs/upload-json/
```

**Request Type:** `form-data`
**Key:** `file`
**Value:** *(Select your JSON file, e.g., `playlist[76].json`)*

The API will parse and normalize the data, then insert it into the database.

---

### Step 3: Test Other API Endpoints

#### ✅ Get All Songs (with pagination)

```http
GET /api/songs/?page=1&limit=20
```

#### 🔍 Search Song by Title

```http
GET /api/songs/search/?title=4 Walls
```

#### ⭐ Rate a Song

```http
PUT /api/songs/rate/
```

**Body (JSON):**

```json
{
  "song_id": "5vYA1mW9g2Coh1HUFUSmlb",
  "rating": 5
}
```

> Replace `"song_id"` with a valid ID from your database.


