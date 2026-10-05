# Staging gate — ตรวจ data quality ที่ staging ก่อน deploy ขึ้น prod

สถานะ: **เตรียมไว้ ยังไม่ทำงาน และยังไม่เคยรันจริง** (ยังไม่มี staging workspace) ใน `.github/workflows/fabric-ci.yml`
มี job ใหม่ 3 ตัวที่ถูกข้ามทั้งหมดจนกว่าจะตั้ง repo variable `STAGING_WORKSPACE_ID`

## ทำไมต้องมี

`dq-gate-poc` รันหลัง `deploy-prod` — ถ้าเจอของเสียก็ขึ้น production ไปแล้ว (ตรวจได้ แต่กันไม่ได้)
`dq-gate-dev` (ตรวจที่ Dev ตอนเปิด PR) เป็นตัวทดแทนชั่วคราว: ผ่านที่ Dev ไม่การันตีว่า prod สะอาด และต้องตั้งเป็น
required check ถึงจะบล็อกได้จริง

เป้าหมายคือลำดับนี้: **PR → deploy ไป staging → ตรวจ DQ ที่ staging → (ผ่านแล้วถึง) merge เข้า main → deploy-prod**

## ลำดับ job เมื่อเปิดใช้งาน (บน pull_request ที่ชี้ `main` หรือ `staging`)

```
test ─┬─ deploy-staging ─┬─ dq-gate-staging        ← gate ตัวจริง (ตั้งเป็น required check)
      │                  └─ verify-staging-guids   ← รายงาน GUID ของ Dev ที่ตกค้าง (ยังไม่บล็อก)
      └─ dq-gate-dev  ← ถูกข้ามอัตโนมัติเมื่อมี STAGING_WORKSPACE_ID
```

บน push เข้า `main` jobs ชุดนี้ไม่รัน (เป็น PR-only) `deploy-prod` ทำงานตามเดิม และ `dq-gate-poc` ยังรันหลัง deploy-prod
เป็นชั้นยืนยัน (ไม่ใช่ gate)

## ขั้นตอนเปิดใช้งาน (ทำตามลำดับ)

1. **สร้าง staging workspace** — แยก Fabric Capacity จาก prod (ดู section 2 ของ `DataOps-CICD-Workflow.md`)
   ต้องขอ IT/ผู้ดูแล capacity
2. **ให้ Service Principal เข้าถึงได้** — SP ที่ใช้ใน `FABRIC_CLIENT_ID` ต้องเป็น Member/Contributor ของ staging
   และ (สำหรับ `verify-staging-guids`) อ่าน Dev workspace ได้ด้วย
3. **ตั้ง repo variable** `STAGING_WORKSPACE_ID` = GUID ของ staging
   (Settings → Secrets and variables → Actions → **Variables** ไม่ใช่ Secrets)
4. **ทดลองด้วย PR ทดลอง** ชี้ `main` (หรือ `staging`) แล้วดูว่า 3 job ผ่านและ `dq-gate-dev` ถูก skip
5. **ตั้ง required status check** บน `main`: เปิด `dq-gate-staging` (และเอา `dq-gate-dev` ออกถ้าเคยตั้งไว้)
   Settings → Branches → branch protection rule ของ `main` → Require status checks
   - ถ้าไม่ตั้ง job แดงแล้วก็ยัง merge ได้ — ไม่ได้เป็น gate จริง
   - job ที่ถูก skip เพราะเงื่อนไข (`if`) GitHub รายงานเป็นผ่านสำหรับ required check ดังนั้นตั้งทั้ง `dq-gate-dev` และ
     `dq-gate-staging` พร้อมกันได้ ตัวที่ไม่ทำงานจะไม่บล็อก — แต่แนะนำเอา `dq-gate-dev` ออกเมื่อเปลี่ยนมาใช้ staging เพื่อไม่ให้สับสน
6. หลัง `verify-staging-guids` รันผ่านเสถียรสองสามครั้ง ให้ลบ `continue-on-error: true` เพื่อให้เป็น gate

## ต้องตัดสินใจ/เช็คก่อนเปิดใช้งาน (ยังไม่ได้แก้ในพีอาร์นี้)

- **rule ของ endpoint ใช้ `_ALL_`** — ใน `fabric_items/parameter.yml` rule ของ `nb_endpoint_test` / `nb_endpoint_test_b`
  แทน workspace/lakehouse id เป็นของ **endpoint-prod** กับทุก environment ถ้า deploy ไป staging item พวกนี้
  จะชี้ endpoint-prod (อ่านจากไฟล์ ยังไม่ได้ทดลอง) ต้องเลือก: ข้าม item กลุ่มนี้ตอน deploy staging, แยก rule ตาม
  environment (`staging:` key) หรือยืนยันว่าไม่มีใครรัน item พวกนี้ใน staging ปัจจุบันทีมใช้เป็น item ทดสอบ
- **ข้อมูลใน staging** — `dq-gate-staging` รัน `pl_dqgate_test` กับ `lh_dqgate_test` ใน staging ต้องแน่ใจว่ามีข้อมูล
  ให้ตรวจ (หรือ pipeline สร้างเองเหมือนที่ prod) ผ่านที่ staging ตรวจได้เท่ากับข้อมูลที่อยู่ใน staging เท่านั้น ยังไม่การันตี prod ทั้งหมด
- **`deploy-endpoints` ไม่ครอบคลุม staging** — `endpoint-targets.yml` มีแค่ `dev` / `prod` ถ้าต้องทดสอบ endpoint ที่ staging
  ต้องเพิ่ม target `staging` และแก้ job ให้รู้จัก environment นี้
- **`scripts/deploy.py` unpublish orphan items** — ทำงานกับ staging ด้วย (Lakehouse/Warehouse ไม่ถูกลบโดย default)
- **`deploy-test-job.yml` (draft เก่า)** — ออกแบบให้ deploy เมื่อ push เข้า branch `staging` ถูกแทนที่ด้วยแนว PR-based
  ในไฟล์ workflow จริงแล้ว เก็บไว้อ้างอิงเท่านั้น

## ข้อจำกัดที่ต้องรู้

- ไม่มี `actionlint` ในเครื่องที่เตรียมไว้ — ตรวจแค่ว่า YAML parse ได้และลำดับ `needs` ตรงตามที่ตั้งใจ
  ไม่ได้รันบน GitHub จริง การทดสอบจริงต้องทำหลังมี staging
- การตรวจที่ staging ไม่แทนที่การดู INFO ของ `verify-staging-guids` — GUID ที่ไม่ใช่ของ Dev/staging (เช่น endpoint) ต้องมีคนดู
