# Refactoring explanation

## 1) Đoạn code gốc làm gì?

Đoạn code:

- Nhận request `POST /api/messages` với `conversationId, bookerId, content, channel` từ `req.body`
- Lấy `conversation` theo `conversationId`
- Tạo `message` (sender = `bookerId`)
- Nếu `content` có keyword `commission/payment` thì tạo `riskFlag`
- Trả về message

## 2) Module CRMchat (FastAPI) tương đương phần nào?

Trong CRMchat, các chức năng “tương đương” được tách ra thành 2 luồng:

### A. Internal app message (Booker/Manager gửi từ workspace)

- Endpoint: `POST /conversations/{conversation_id}/messages`
- Source identity: lấy từ **auth context** (header `X-User-Id` trong MVP)
- Permission: check conversation owner/team
- Side effects: tạo `AuditLog`, và risk detection (MVP đã có keyword risk trong `risk/evaluate` và webhook ingest; rule engine có keyword money)

### B. Webhook message (tin nhắn inbound từ kênh ngoài)

- Endpoint: `POST /webhooks/{channel}`
- Verify secret/signature (mock): `X-Webhook-Secret`
- Deduplicate: theo `(channel, external_message_id)`
- Map external sender → `KOC` placeholder (nếu chưa có)
- Save raw payload: `WebhookRawEvent` (luôn lưu, kể cả reject)
- Save message vào conversation (tìm/hoặc tạo conversation)
- Risk: tạo `RiskFlag` khi có keyword nhạy cảm (ví dụ “commission riêng”)

## 3) Mapping


| Node snippet              | CRMchat module                                                                                          |
| ------------------------- | ------------------------------------------------------------------------------------------------------- |
| `conversationId`          | `conversation_id` (UUID)                                                                                |
| `bookerId` (body)         | `X-User-Id` (auth context) với internal message; webhook dùng `assigned_booker_id` trong payload (mock) |
| `channel` string          | `Channel` enum: `whatsapp`, `telegram`                                                                  |
| `content`                 | `Message.body` (text)                                                                                   |
| `db.messages.create(...)` | `Message` insert + audit (và risk tùy rule)                                                             |
| `riskFlags.create(...)`   | `RiskFlag` insert (rule-based)                                                                          |
| (không có)                | `AuditLog` append-only ở mức API                                                                        |
| (không có)                | `WebhookRawEvent` (raw event immutable log)                                                             |
| (không có)                | `ExternalMessageRef` để dedupe webhook                                                                  |


## 4) Refactoring Checklist

### 4.1 Tách controller / service / repository

- **Hiện có**:
  - `app/main.py`: router/controller layer (FastAPI endpoints)
  - `app/service.py`: service layer (business rules + DB writes/reads)
  - repository/DAO layer riêng (DB query hiện ở `service.py`)

### 4.2 Lấy user từ auth context (không tin `bookerId` từ body)

- Internal message endpoint **không nhận** `bookerId` trong body.
- Auth MVP đang dùng `X-User-Id` header để mô phỏng `req.user.id`.
- internal message lấy user từ auth context → server kiểm soát identity
- webhook inbound không có user context nên dùng `external_sender_id` + mapping sang KOC; booker assignment (mock) chỉ dùng để route conversation, không phải “sender”.

### 4.3 Validate request body

- Dùng Pydantic schema:
  - `MessageCreate`, `ConversationCreate`, `WebhookMessageIn`, `DealUpsert`…

### 4.4 Permission check theo conversation owner/team

- Service function `ensure_conversation_access()`:
  - Booker chỉ được thao tác conversation `assigned_booker_id == user.id`
  - Manager chỉ thao tác conversation thuộc `team_id == user.team_id`

### 4.5 Transaction khi create message + risk flag + audit log

- Internal message (`add_message`): đã wrap trong transaction (message + audit + risk flag) bằng 1 block try/except → session.commit 1 lần.
- Webhook ingest: đã đưa toàn bộ tạo message, external ref, audit, risk, raw.accept trong 1 transaction, chỉ commit 1 lần.

### 4.6 Deduplicate webhook bằng `external_message_id`

- Có `ExternalMessageRef` unique `(channel, external_message_id)`
- Logic ingest trả `deduplicated=true` khi trùng

### 4.7 Normalize channel enum

- `Channel` enum được dùng trong models + webhook route + external ref

### 4.8 Audit log immutable

- **Đạt ở mức API**: không có endpoint update/delete audit.
- **Chưa harden ở mức DB**: chưa có constraint/trigger chống update/delete trực tiếp, sẽ thêm trên DB thật

### 4.9 Error code rõ ràng

- 401 (webhook secret), 403 (permission), 404 (not found), 400 (validation/mismatch), 409 (conflict)

### 4.10 Unit tests cho permission, duplicate, risk flag, transaction rollback

- **Đã có**:
  - Permission: `tests/test_rbac_audit.py`
  - Webhook secret reject + raw saved, dedupe, placeholder KOC, keyword risk: `tests/test_webhooks.py`
  - Risk engine rules: `tests/test_risk_engine.py`
- **Chưa có**:
  - Transaction rollback tests

