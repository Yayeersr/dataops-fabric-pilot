# Staging gate — ตรวจ data quality ที่ staging ก่อน deploy ขึ้น prod

สถานะ: **เตรียมไว้ ยังไม่ทำงาน และยังไม่เคยรันจริง** (ยังไม่มี staging workspace) ใน `.github/workflows/fabric-ci.yml`
มี job ใหม่ 3 ตัวที่ถูกข้ามทั้งหมดจนกว่าจะตั้ง repo variable `STAGING_WORKSPACE_ID`

## ทำไมต้องมี

`dq-gate-poc` รันหลัง `deploy-prod` — ถ้าเจอของเสียก็ขึ้น production ไปแล้ว (ตรวจได้ แต่กันไม่ได้)
`dq-gate-dev` (ตรวจที่ Dev ตอนเปิด PR) ผ่านที่ Dev ไม่การันตีว่า prod สะอาด และต้องตั้งเป็น required check ถึงจะบล็อกได้จริง

เป้าหมาย: **ตรวจ DQ ก่อน deploy ไป workspace ถัดไปทุกครั้ง** — Dev gate → staging → staging gate → prod

## ลำดับ pipeline (gate อยู่ก่อน deploy ไป workspace ถัดไปเสมอ)

```
test → dq-gate-dev → deploy-staging ─┬─ dq-gate-staging ──────┬─ deploy-prod → dq-gate-poc
                                     ├─ deploy-endpoints-staging ┤
                                     └─ verify-staging-guids     └─ deploy-endpoints (prod/dev)
                                        (รายงาน ไม่บล็อก)
```

| job | รันเมื่อ | บทบาท |
|---|---|---|
| `dq-gate-dev` | `pull_request` → `main`/`staging` | gate ที่ Dev ก่อน deploy ไป staging (ตั้งเป็น required check ได้) |
| `deploy-staging` | PR → `main`/`staging` **และ** push เข้า `main` เมื่อมี `STAGING_WORKSPACE_ID` | deploy ไป staging |
| `dq-gate-staging` | หลัง `deploy-staging` สำเร็จ (PR และ push) | gate ที่ staging ก่อน deploy ไป prod |
| `deploy-prod` / `deploy-endpoints` (prod) | push เข้า `main` | **ไม่รันถ้า `deploy-staging`, `dq-gate-staging` หรือ `deploy-endpoints-staging` ล้มเหลว** |
| `deploy-endpoints-staging` | หลัง `deploy-staging` สำเร็จ | deploy endpoint item เข้า endpoint workspace ของ staging (no-op จนกว่าจะใส่ target `staging`) |
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

## Endpoint workspace ของ staging (เตรียมไว้ — ยังไม่เปิดใช้)

ถ้ามี staging ก็ต้องมี endpoint workspace ฝั่ง staging ด้วย (คู่ขนานกับ `spl-cicd-endpoint-dev` / `-prd`) เพื่อทดสอบงาน
cross-workspace (`pl_endpoint_test*`) ก่อนขึ้น prod หมายเหตุ: `pl_dqgate_test` (ตัวที่ DQ gate รัน) **ไม่พึ่ง endpoint**
ดังนั้น staging ที่ยังไม่มี endpoint workspace ก็รัน DQ gate ได้ — endpoint staging จำเป็นเมื่อต้องการยืนยัน item กลุ่ม endpoint ด้วย

ที่เตรียมไว้แล้ว (ไม่ทำงานจนกว่าจะเปิด):
- `deploy-endpoints-staging` ใน `fabric-ci.yml` — อ่านเป้าหมายจาก `targets.staging` ใน `endpoint-targets.yml`
  (ถ้าไม่มี target ไหน สคริปต์พิมพ์ notice แล้วจบแบบไม่ผิดพลาด) และ `deploy-prod` / `deploy-endpoints` รอผลของ job นี้
- `endpoint-targets.yml` — มีคอมเมนต์ `# staging: <GUID>` ในทุก entry
- rule ของ `nb_endpoint_test` / `nb_endpoint_test_b` ใน `parameter.yml` เปลี่ยนจาก `_ALL_` เป็น key `prod`
  (ค่าเดิมทุกตัว deploy-prod ส่ง `--environment prod` ผลจึงเหมือนเดิม) เพื่อกัน staging ถูก remap ไปชี้ endpoint-**prod**
  — ตามซอร์สโค้ด fabric-cicd ถ้า environment ไม่มี key นั้น rule จะถูกข้ามพร้อม warning (ไม่ error) staging จึงคงค่าเดิมของ endpoint-dev

ขั้นตอนเปิดใช้ (หลังมี staging workspace หลักแล้ว):
1. สร้าง endpoint workspace ของ staging (เช่น `spl-cicd-endpoint-stg`) ให้ SP เข้าถึง และอยู่บน capacity ที่แยกจาก prod
2. `endpoint-targets.yml`: เอาคอมเมนต์ `# staging:` ออกและใส่ GUID ของ workspace นั้น (ทุก entry ที่ต้อง deploy ไป staging)
3. `parameter.yml`: เพิ่มบรรทัด `staging:` ใน rule ของ `nb_endpoint_test*` ทั้ง 4 ตัว (workspace id และ lakehouse id ของ endpoint staging)
   ⚠️ id ที่ hardcode พังเมื่อ lakehouse ถูกสร้างใหม่ (เกิดแล้วกับ rule ของ prod) ถ้าเลี่ยงได้ให้ notebook หา lakehouse จากชื่อตอนรัน
   (ต้องแก้ผ่าน Fabric UI และยังไม่ได้ทดสอบ)
4. `verify-staging-guids`: เพิ่ม `--allow <GUID ของ endpoint staging workspace>` ใน workflow เพื่อไม่ให้ขึ้นเป็น INFO ทุกครั้ง
5. รัน `scripts/debug_parameterization.py --environment staging` เช็คโครงสร้าง แล้วทดสอบด้วย PR ทดลอง

## ต้องตัดสินใจ/เช็คก่อนเปิดใช้งาน

- **ข้อมูลใน staging** — `dq-gate-staging` รัน `pl_dqgate_test` กับ `lh_dqgate_test` ใน staging ต้องแน่ใจว่ามีข้อมูล
  ให้ตรวจ (หรือ pipeline สร้างเองเหมือนที่ prod) ผ่านที่ staging ตรวจได้เท่ากับข้อมูลที่อยู่ใน staging เท่านั้น ยังไม่การันตี prod ทั้งหมด
- **`scripts/deploy.py` unpublish orphan items** — ทำงานกับ staging ด้วย (Lakehouse/Warehouse ไม่ถูกลบโดย default)
- **`deploy-test-job.yml` (draft เก่า)** — ออกแบบให้ deploy เมื่อ push เข้า branch `staging` ถูกแทนที่ด้วยแนว PR-based
  ในไฟล์ workflow จริงแล้ว เก็บไว้อ้างอิงเท่านั้น

## ข้อจำกัดที่ต้องรู้

- ไม่มี `actionlint` ในเครื่องที่เตรียมไว้ — ตรวจแค่ว่า YAML parse ได้และลำดับ `needs` ตรงตามที่ตั้งใจ
  ไม่ได้รันบน GitHub จริง การทดสอบจริงต้องทำหลังมี staging
- การตรวจที่ staging ไม่แทนที่การดู INFO ของ `verify-staging-guids` — GUID ที่ไม่ใช่ของ Dev/staging (เช่น endpoint) ต้องมีคนดู
