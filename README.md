# dataops-fabric-pilot

Pilot repo ที่พิสูจน์ mechanism ของ CI/CD สำหรับ Microsoft Fabric — ใช้ GitHub Actions + [`fabric-cicd`](https://github.com/microsoft/fabric-cicd) เป็นตัวขับเคลื่อนหลัก ดูดีไซน์เต็มได้ที่ `DataOps-CICD-Workflow.md` (repo เอกสารแยก) — README นี้เป็น cheat-sheet สำหรับ onboard คนในทีมเข้าใจ repo นี้เร็ว ๆ

---

## ไฟล์ที่ใช้ในระบบ

### CI (เช็คก่อน merge) — ขาดไม่ได้

| ไฟล์ | หน้าที่ |
|---|---|
| `.github/workflows/fabric-ci.yml` | ตัว workflow ที่รันจริงทุก push/PR |
| `ci-config.yml` | กฎว่า item ไหนต้องเช็คแบบไหน (`unit_test` / `data_quality` / `structure` / `schema` / `none`) |
| `requirements.txt` | dependency ที่ CI ต้องติดตั้งก่อนรันเช็ค |
| `tests/unit/test_<name>.py` | test คู่กับ Notebook แต่ละตัว (ชื่อต้องตรงชื่อ item เป๊ะ) |
| `great_expectations/checkpoints/dq_<name>.yml` | checkpoint คู่กับ item ที่ check = `data_quality` |
| `scripts/validate_pipeline_structure.py`, `validate_schema_contract.py` | script กลางสำหรับ check = `structure` / `schema` |
| `schema_contracts/<name>.yml` | contract คู่กับ item ที่ check = `schema` (Lakehouse/Warehouse) — ประกาศ table/column/type ที่คาดหวังไว้ ชื่อไฟล์ต้องตรงชื่อ item เป๊ะ เหมือน `tests/unit/test_<name>.py`; เช็คได้แค่ "มี contract ประกาศไว้ไหม + format ถูกไหม" เท่านั้น ไม่ได้เทียบกับ schema จริงบน Fabric (Git Integration ไม่ sync ข้อมูลนี้มาให้) — ดูวิธีใช้เต็มที่ [`docs/check-patterns-guide.md`](docs/check-patterns-guide.md) (ส่วนที่ 2) ตัวอย่างจริงที่ `schema_contracts/lh_dqgate_test.yml` |

### CD (deploy จริง) — ขาดไม่ได้

| ไฟล์ | หน้าที่ |
|---|---|
| `scripts/deploy.py` | publish item เข้า workspace ปลายทาง + ลบ item เก่าที่หายจาก repo |
| `fabric_items/` | payload จริงที่จะถูก deploy (sync มาจาก Fabric Git Integration) |
| `fabric_items/parameter.yml` | remap GUID (lakehouse/workspace) ให้ตรง environment ปลายทาง — ต้องมีตั้งแต่มี Notebook ตัวแรกที่ attach lakehouse |

### เครื่องมือเสริม — ไม่มีก็รันได้ แต่ช่วยลดงานมือ

| ไฟล์ | หน้าที่ | ใช้ตอนไหน |
|---|---|---|
| `scripts/generate_ci_config.py` | bulk-generate `ci-config.yml` จาก item ที่มีจริง | ตอน onboard item จำนวนมากครั้งแรก |
| `scripts/generate_parameter.py` | bulk-generate `parameter.yml` จาก metadata ที่ Fabric ฝังไว้ใน notebook | หลังเพิ่ม Notebook ที่ attach lakehouse ใหม่ |
| `scripts/debug_parameterization.py` | validate `parameter.yml` แบบ offline ไม่ต้องมี Azure credential | ก่อน push เช็ค syntax เร็ว ๆ |
| `scripts/generate_parameter_all_types.py` | หา GUID ที่ต้อง remap ทุก item type โดยเทียบกับ item จริงใน Dev ผ่าน Fabric REST API (แยก logicalId ที่ `fabric-cicd` จัดการให้เองออกจาก GUID ที่ต้องดูเอง) ต้องมี credential อ่าน Dev ได้ | หลังเพิ่ม item ใหม่ที่อาจฝัง GUID ของ Dev — รัน `--dry-run` ก่อนเสมอ |
| `scripts/verify_deployed_guids.py` | ตรวจหลัง deploy ว่าไม่มี GUID ของ Dev ตกค้างใน item ของ target (อ่านอย่างเดียว) — PASS แปลว่าไม่ชี้กลับ Dev ไม่ได้พิสูจน์ว่าชี้ถูกที่ GUID ที่ขึ้น INFO ต้องมีคนตรวจ ใช้เวลา ~2.5 นาที | หลัง deploy ไป prod ทุกครั้ง |
| `scripts/run_live_dq_gate.py` | สั่งรัน pipeline ที่มี live GX check ข้างในผ่าน Fabric REST API + รอผล | ทำ data quality gate ที่เช็คข้อมูลจริงบน Fabric (ไม่ใช่ CSV fixture) — ดูวิธีใช้เต็มที่ [`docs/check-patterns-guide.md`](docs/check-patterns-guide.md) (ส่วนที่ 1) |

### ยังไม่ได้ใช้จริง (draft)

| ไฟล์ | สถานะ |
|---|---|
| `deploy-test-job.yml` | รอสร้าง staging workspace ก่อนถึงจะเอาไปรวมเข้า `fabric-ci.yml` ได้ |

---

## ข้อจำกัด/กฎที่ต้องรู้ก่อนเริ่มงาน

1. **สร้าง item ผ่าน Fabric UI หรือ MCP เท่านั้น** — ห้าม hand-write ไฟล์ item ตรงเข้า `fabric_items/` เอง (logicalId จะไม่ตรง ทำให้ Fabric sync conflict) MCP ใช้ได้ (ยืนยันแล้วกับ Notebook/Lakehouse) แต่ยังต้องกด **Commit ผ่าน Fabric UI (Source Control panel) เสมอ** ไม่ว่าจะสร้างวิธีไหน

2. **ชื่อไฟล์ test ต้องตรงชื่อ item เป๊ะ** — `nb_xxx.Notebook` ↔ `tests/unit/test_xxx.py` ไม่ตรง CI หาไม่เจอ error ทันที

3. **`ci-config.yml` เป็น fail-safe เข้ม** — ไม่ระบุ = ต้องมี unit test เสมอ (default) ถ้าจะข้ามต้องเขียน `skip_check: true` + `skip_reason` เสมอ ห้ามปล่อยว่าง ไม่งั้น CI fail แทนที่จะผ่านเงียบ ๆ

4. **`parameter.yml` ระวัง environment key พิมพ์ผิด** — ถ้า key (`dev`/`staging`/`prod`) ไม่ตรงกับที่ `deploy.py --environment` ส่งเข้าไป **fabric-cicd จะข้าม rule นั้นไปเงียบ ๆ ไม่ error เตือน** ต้องเช็คเอง

5. **External Connection (Dataflow/Copy Activity) ยังมีปัญหาจริง** — Service Principal ที่ deploy ไม่มีสิทธิ์บน Connection object ทำให้ deploy prod fail เสมอ ตอนนี้ทีมเลี่ยงด้วยการใช้ Notebook Activity แทน Copy Activity (ยังไม่ verify ว่า Deployment Rules แก้ได้จริงหรือเปล่า — รอ permission มา test)

6. **Staging workspace ยังไม่มีจริง** — merge เข้า `staging` ตอนนี้ผ่านแค่ check ไม่มี deploy จริงเกิดขึ้น

7. **Deploy-prod ต้องมี manual approval** — ตั้งไว้ที่ GitHub Environment protection ก่อน push เข้า `main` จะไม่ deploy ทันที

8. **Rollback ข้อมูล (ไม่ใช่ code) เป็น manual process เสมอ** — มี `nb_rollback_helper` (draft) ช่วย automate แต่การตัดสินใจ/ยืนยัน version ที่จะ restore ต้องเป็นคนเสมอ ไม่ trigger อัตโนมัติ

9. **`skip_check` ที่เกิดจาก bulk onboarding คือหนี้เทคนิค** ไม่ใช่คำตอบถาวร — ต้องมีคนกลับมาเขียน test จริงแล้วเอา flag ออกทีหลัง
