# Coding Agent: Cursor

**User**

Tôi đang xây dựng phần mềm nội bộ dạng Chat CRM để quản lý đội booking KOC/KOL.
Hiện tại Booker đang:

- Lưu KOC trên Google Sheet
- Chat với KOC qua WhatsApp, Viber, Zalo, Telegram, Instagram, TikTok DM
- Follow-up thủ công
- Discuss giá/commission/deal terms qua nhiều kênh rời rạc
- Approval không có bằng chứng hội thoại đầy đủ
- Manager khó biết Booker nào đang xử lý KOC nào
- Có rủi ro gian lận: Booker/KOC discuss riêng về giá, deal, payment hoặc commission ngoài hệ thống

Tôi muốn build một hệ thống nơi nhân viên booking phải:

-Đăng nhập hoặc kết nối tài khoản chat qua nền tảng nội bộ, hoặc dùng extension được công ty quản lý

- Chat với KOC trong workspace nội bộ
- Mọi hội thoại, giá, deal terms, file, ảnh chụp, voice note, approval evidence được lưu lại
- Hệ thống detect conversation liên quan đến tiền/giá/commission/deal terms
- Manager có thể audit toàn bộ lifecycle từ contact → negotiation → approval → close

Bạn hãy Thiết kế MVP backend/system cho phần mềm Omni-channel Chat CRM cho đội Booking KOC/KOL.
Hệ thống cần hỗ trợ:
1 KOC CRM Database
2 Booker account management
3 Channel account connection: WhatsApp, Viber, Telegram, Zalo, Instagram, TikTok
4 Conversation inbox
5 Message sync / webhook ingestion
6 Manual chat log / browser extension fallback
7 CRM pipeline status
8 Follow-up reminder
9 Fraud/risk detection
10 Manager audit dashboard

---

**User**

Use python generate API:

- Create conversation
- Add message
- List conversations by Booker
- List messages by conversation
- Attach message to KOC + campaign
- Mark conversation status
- Create audit log khi add message/status change

Test cases:

- Booker chỉ xem được conversation của mình
- Manager xem được conversation của team
- Không add message vào conversation không thuộc quyền
- Mỗi message phải có immutable audit log
- Conversation phải gắn với KOC và campaign

---

**User**

 Build mock webhook receiver for 2 channel, ex: WhatsApp amd Telegram.
API:

- Receive webhook event
- Verify webhook signature/mock secret
- Deduplicate by external_message_id
- Map external sender → KOC profile
- Save message into conversation
- Store raw webhook payload
- Create risk flag if message have sensitive keyword

Test cases:

- Webhook sai secret bị reject
- Duplicate external_message_id không tạo message lần hai
- Sender mới tạo KOC/contact placeholder
- Message có keyword “commission riêng” tạo risk flag
- Raw event được lưu để audit/debug

---

**User**

Build module detect risk in conversation.  
Input:
- Conversation messages  
- Deal price  
- Approval status  
- KOC benchmark price  
- Pipeline status

Output:
- Risk flags
Rules:
- Price changed but no price discussion in chat
- Deal closed without KOC confirmation message
- Message contains sensitive money keywords
- Final price > 150% benchmark
- Approval requested after commitment message was sent

Test cases:
- Không tạo risk nếu chat có price evidence hợp lệ
- Tạo risk nếu final price đổi nhưng chat không nhắc giá
- Tạo risk nếu có keyword nhạy cảm
- Tạo risk nếu price vượt benchmark
- Tạo risk nếu commit trước approval

---

**User**

create dockerfile docker-compose

---

**User**

@tests/test_rbac_audit.py:1-153 testcase did not check mapping between conversation and KOC, campaign
add test cases and verify part to ensure mapping between conversation and KOC, campaign

---

**User**

 @REFACTORING_EXPLANATION.md:77-82 check and refactor to wrap transaction when create message, risk flag and audit log

---

**User**

add testcase Transaction rollback