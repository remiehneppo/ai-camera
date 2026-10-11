---
status: accepted
---

# FastAPI/Python và MongoDB cho backend

Ngày 2026-10-11, người dùng chọn FastAPI/Python và MongoDB, thay đề xuất PostgreSQL. Giữ event revision/current projection và outbox intent atomic trong transaction, unique compound index cho device/event/revision, conditional version update cho review và ACK sau durable commit; đổi database không hạ contract idempotency/durability.

Multi-document transactions cần deployment hỗ trợ transactions; standalone không phù hợp. Q18 chốt replica set một member với persistent volume cho lab, có bootstrap/readiness và transaction/retry tests; không coi là HA, production HA/backup vẫn là gate riêng. Evidence nằm ngoài MongoDB với pending/finalize/reconciliation, không giả transaction chung DB/file. Tham khảo [transaction requirements](https://www.mongodb.com/docs/manual/core/transactions-production-consideration/) và [write concern](https://www.mongodb.com/docs/manual/reference/write-concern/).
