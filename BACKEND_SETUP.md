# Backend Setup Guide

## Overview
This backend is built with FastAPI and serves ticker data to the React frontend. It's designed to be database-agnostic and can integrate with PostgreSQL when the database is ready.

## Prerequisites
- Python 3.8+
- pip

## Installation

1. **Create a virtual environment** (recommended):
   ```bash
   python -m venv backend_env
   
   # Activate it
   # On Windows:
   backend_env\Scripts\activate
   # On macOS/Linux:
   source backend_env/bin/activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r backend/requirements.txt
   ```

## Running the Backend

```bash
python backend/main.py
```

The API will be available at `http://localhost:8000`

### Interactive API Documentation
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## API Endpoints

### GET `/api/health`
Health check endpoint.

**Response**:
```json
{ "status": "ok" }
```

### GET `/api/tickers`
Get list of all available ticker symbols.

**Response**:
```json
{
  "tickers": ["AAPL", "GOOGL", "MSFT", ...],
  "count": 16
}
```

### GET `/api/tickers/{symbol}`
Get payload data for a specific ticker.

**Parameters**:
- `symbol` (string): Ticker symbol (case-insensitive)

**Response**:
```json
{
  "meta": {...},
  "hedging": {...},
  "explainability": {...},
  "charts": {...},
  "opportunities": [...]
}
```

**Error Responses**:
- `404`: Ticker not found
- `500`: Server error

## PostgreSQL Integration (TODO)

When ready to integrate with PostgreSQL:

1. **Install dependencies**:
   ```bash
   pip install psycopg2-binary sqlalchemy pydantic-sqlalchemy python-dotenv
   ```

2. **Create a database models file** (`backend/models.py`):
   ```python
   from sqlalchemy import Column, String, JSON
   from sqlalchemy.orm import declarative_base
   
   Base = declarative_base()
   
   class Ticker(Base):
       __tablename__ = "tickers"
       
       symbol = Column(String(10), primary_key=True)
       payload = Column(JSON, nullable=False)
   ```

3. **Update main.py to use database**:
   - Replace file-based data loading with database queries
   - Add connection pooling
   - Implement caching for frequently accessed tickers

4. **Create a `.env` file** with database credentials:
   ```
   DATABASE_URL=postgresql://user:password@localhost:5432/volarbear
   ```

5. **Update CORS origins** if deploying to production

## Frontend Configuration

The frontend is configured to communicate with the backend at `http://localhost:8000`. 

To change the API base URL, update `app/utils/tickers.ts`:

```typescript
const API_BASE_URL = "http://localhost:8000/api";
```

## Development Notes

- The API serves JSON files from `app/assets/data/` directory
- Files should be named `{SYMBOL}_Payload.json`
- CORS is enabled for local development (ports 5173 and 3000)
- Add additional routes for new features as needed
