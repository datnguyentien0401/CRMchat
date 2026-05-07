# CRMchat MVP (FastAPI)

## Run (dev)

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
uvicorn app.main:app --reload
```

Auth (MVP) dùng header:
- `X-User-Id`: `booker-1`, `booker-2`, `manager-1`

## Test

```bash
pytest -q
```

## Run with Docker

```bash
docker compose up --build
```

API: `http://localhost:8000`

