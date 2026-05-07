## Code review notes — `POST /api/messages` 

```js
app.post('/api/messages', async (req, res) => {
  const { conversationId, bookerId, content, channel } = req.body;
 
  const conversation = await db.conversations.findFirst({
	where: { id: conversationId }
  });
 
  if (!conversation) {
	return res.status(404).json({ message: 'Conversation not found' });
  }
 
  const message = await db.messages.create({
	data: {
  	conversationId,
  	senderId: bookerId,
  	channel,
  	content,
  	createdAt: new Date()
	}
  });
 
  if (content.includes('commission') || content.includes('payment')) {
	await db.riskFlags.create({
  	data: {
    	conversationId,
    	type: 'MONEY_DISCUSSION',
    	messageId: message.id
  	}
	});
  }
 
  return res.json(message);
});

```

---

## 1) Vì sao không được tin `bookerId` từ request body?

- **Rủi ro impersonation**: client có thể giả mạo `bookerId` để gửi tin nhắn “thay mặt” người khác.
- **Cách đúng**: `bookerId` phải lấy từ **auth context** (JWT/session) như `req.user.id`, không lấy từ body.
- **Nếu cần “send as”**: phải có **server-side mapping + permission** rõ ràng (không cho client quyết định sender).

---

## 2) Thiếu permission check ở đâu?

Ngay sau khi load `conversation`, cần check:

- **Booker**: `conversation.assignedBookerId === req.user.id`
- **Manager** (nếu manager được gửi): `conversation.teamId === req.user.teamId`
- **Channel policy**: `channel` có thuộc quyền/được connect cho user/team không.

---

## 3) Booker có thể ghi message vào conversation của người khác không?

**Có**. Vì hiện tại:

- Chỉ check conversation tồn tại (404).
- **Không** check ownership/assignment/team.
- Lại còn cho truyền `bookerId` tuỳ ý → vừa **write vào conversation người khác**, vừa **mạo danh sender**.

---

## 4) Có cần transaction giữa message và risk flag không?

**Nên có** nếu coi risk flag là “bằng chứng đồng bộ” của message:

- Nếu tạo message xong tạo risk flag fail → **message có nhưng risk không có** (inconsistent).

Nếu chấp nhận eventual consistency (job queue) thì cần:

- log lỗi + retry
- đánh dấu trạng thái kiểu `risk_scan_pending`

Nếu xử lý sync như hiện tại: dùng **DB transaction** (Prisma `$transaction`).

---

## 5) Keyword detection như vậy có đủ không?

**Không đủ**, vì:

- **Case-sensitive** (`Commission`, `PAYMENT` không match)
- **False negative**: “ck”, “chuyển khoản”, “hoa hồng”, “giá”, “%”, “USD”, “10tr”, “inbox giá”…
- **False positive**: quote lại người khác, hoặc “payment link” unrelated

MVP tốt hơn:

- normalize `content.toLowerCase()`
- dictionary + regex cho số tiền/%, currency, bank terms
- xét ngữ cảnh nhiều message + scoring severity

---

## 6) Có cần audit log không?

**Có** (compliance/fraud).

Audit tối thiểu (append-only):

- `message_created` (actor, conversationId, messageId, timestamp, channel)
- `risk_flag_created`

Audit cần **không cho sửa/xoá qua API** (immutable).

---

## 7) Có cần sanitize/encrypt content không?

- **Sanitize/XSS**: nếu content hiển thị lên web UI, phải escape khi render; không tin HTML.
- **Encrypt**:
  - nếu có dữ liệu nhạy cảm (payment/bank) → cân nhắc encryption at rest (DB-level hoặc app-level KMS)
  - tối thiểu: access control + logging
- **PII masking** theo role (tuỳ policy).

---

## 8) Có cần attachment/media support không?

Với CRM chat thực tế: **cần** (file/ảnh/voice note).

Schema gợi ý:

- `messages` (text, metadata)
- `attachments` (objectStorageKey, mime, size, checksum)

Upload nên qua presigned URL hoặc media service; tránh nhét binary vào DB.

---

## 9) Error handling có đủ không?

Hiện tại **thiếu**:

- Validate input (missing/invalid types/empty content)
- Try/catch để trả 500 có cấu trúc + logging
- Rate limit / spam protection
- Handling DB failures (create message ok, create risk fail)
- Check `content` có phải string không (tránh crash khi `.includes`)

Error codes nên chuẩn hoá:

- **400** validation
- **403** permission
- **404** not found
- **409** conflict (conversation closed, …)

---

## 10) Nếu message đến từ webhook bên ngoài thì schema khác gì?

Webhook inbound thường cần:

- `externalMessageId` (id từ provider) để **dedupe**
- `provider/channelAccountId/threadId`
- `externalSenderId` + mapping sang KOC
- `direction: inbound`
- `rawPayloadRef` (link raw event)

`senderId` lúc này **không phải bookerId**; thường là `null` hoặc `kocId`.

---

## 11) Có cần immutable raw event log không?

**Có** để audit/debug/chống gian lận.

Raw event log nên lưu:

- payload gốc (JSON)
- verified signature?
- accepted/rejected reason
- timestamps
- external ids

Thiết kế nên **append-only**, không update/delete (hoặc tách “processing result” riêng).

---

## 12) Refactor thành controller/service/repository thế nào?

Gợi ý tách lớp:

- **Controller** (`messages.controller.ts`)
  - parse/validate request
  - lấy `req.user`
  - gọi service
  - map response
- **Service** (`messages.service.ts`)
  - `assertCanPostMessage(user, conversation)`
  - `createMessageAndSideEffects()` (transaction)
  - gọi `riskEngine.scanMessage(...)`
  - tạo audit event
- **Repository** (`messages.repo.ts`, `conversations.repo.ts`)
  - DB queries thuần (Prisma)
- **Risk module** (`risk.service.ts`)
  - rule-based detection + severity + output flags

