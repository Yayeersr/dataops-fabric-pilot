# Staging gate — ตรวจ data quality ที่ staging ก่อน deploy ขึ้น prod

สถานะ: **เตรียมไว้ ยังไม่ทำงาน และยังไม่เคยรันจริง** (ยังไม่มี staging workspace) ใน `.github/workflows/fabric-ci.yml`
มี job ใหม่ 3 ตัวที่ถูกข้ามทั้งหมดจนกว่าจะตั้ง repo variable `STAGING_WORKSPACE_ID`

## ทำไมต้องมี

`dq-gate-poc` รันหลัง `deploy-prod` — ถ้าเจอของเสียก็ขึ้น production ไปแล้ว (ตรวจได้ แต่กันไม่ได้)
`dq-gate-dev` (ตรวจที่ Dev ตอนเปิด PR) ผ่านที่ Dev ไม่การันตีว่า prod สะอาด และต้องตั้งเป็น required check ถึงจะบล็อกได้จริง

เป้าหมาย: **ตรวจ DQ ก่อน deploy ไป workspace ถัดไปทุกครั้ง** — Dev gate → staging → staging gate → prod

## ลำดับ pipeline (gate อยู่ก่อน deploy ไป workspace ถัดไปเสมอ)

```
test → dq-gate-dev → deploy-staging ─┬─ dq-gate-staging ─┬─ deploy-prod → dq-gate-poc
                                     └─ verify-staging-guids (รายงาน ไม่บล็อก)
                                                         └─ deploy-endpoints (รอ gate เดียวกับ deploy-prod)
```

| job | รันเมื่อ | บทบาท |
|---|---|---|
| `dq-gate-dev` | `pull_request` → `main`/`staging` | gate ที่ Dev ก่อน deploy ไป staging (ตั้งเป็น required check ได้) |
| `deploy-staging` | PR → `main`/`staging` **และ** push เข้า `main` เมื่อมี `STAGING_WORKSPACE_ID` | deploy ไป staging |
| `dq-gate-staging` | หลัง `deploy-staging` สำเร็จ (PR และ push) | gate ที่ staging ก่อน deploy ไป prod |
| `deploy-prod` / `deploy-endpoints` (prod) | push เข้า `main` | **ไม่รันถ้า `deploy-staging` หรือ `dq-gate-staging` ล้มเหลว** |
| `dq-gate-poc` | หลัง `deploy-prod` | ยืนยันหลัง deploy (ไม่ใช่ gate) |

สองชั้นกัน: (1) บน PR gate ที่ staging เป็น required check ก่อน merge (2) บน push เข้า `main` run เดียวกันรัน
staging ซ้ำก่อน `deploy-prod` — ชั้นนี้กันของเสียขึ้น prod แม้ไม่ได้ตั้ง required check (แลกกับ deploy staging 2 ครั้งต่อ release)
บน push เข้า `dev` gate พวกนี้เป็น `skipped` ตามปกติ และ `deploy-endpoints` ไป dev ได้เหมือนเดิม

ตอนนี้ (ยังไม่ตั้ง `STAGING_WORKSPACE_ID`): `deploy-staging` / `dq-gate-staging` / `verify-staging-guids` เป็น `skipped`
ซึ่งยอมรับได้ใน `needs` ของ `deploy-prod` จึงทำงานเหมือนก่อนหน้า

## ขั้นตอนเปิดใช้งาน (ทำตามลำดับ)

1. **สร้าง staging workspace** — แยก Fabric Capacity จาก prod (ดู section 2 ของ `DataOps-CICD-Workflow.md`)
   ต้องขอ IT/ผู้ดูแล capacity
2. **ให้ Service Principal เข้าถึงได้** — SP ที่ใช้ใน `FABRIC_CLIENT_ID` ต้องเป็น Member/Contributor ของ staging
   และ (สำหรับ `verify-staging-guids`) อ่าน Dev workspace ได้ด้วย
3. **ตั้ง repo variable** `STAGING_WORKSPACE_ID` = GUID ของ staging
   (Settings → Secrets and variables → Actions → **Variables** ไม่ใช่ Secrets)
4. **ทดลองด้วย PR ทดลอง** ชี้ `main` (หรือ `staging`) แล้วดูว่า `dq-gate-dev` → `deploy-staging` → `dq-gate-staging` รันตามลำดับ และทดลอง push เข้า `main` ครั้งแรกโดยดูว่า `deploy-prod` รอผล gate (เช็คกรณีล้มเหลวด้วยการทำให้ gate แดงหนึ่งครั้ง)
5. **ตั้ง required status check** บน `main`: `dq-gate-dev` และ `dq-gate-staging`
   Settings → Branches → branch protection rule ของ `main` → Require status checks
   - ถ้าไม่ตั้ง job แดงแล้วก็ยัง merge ได้ — แต่ `deploy-prod` ยังถูกบล็อกตอน push (ชั้นที่สอง)
   - job ที่ถูก skip เพราะเงื่อนไข (`if`) GitHub รายงานเป็นผ่านสำหรับ required check
6. หลัง `verify-staging-guids` รันผ่านเสถียรสองสามครั้ง ให้ลบ `continue-on-error: true` เพื่อให้เป็น gate

## ต้องตัดสินใจ/เช็คก่อนเปิดใช้งาน (ยังไม่ได้แก้)

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
