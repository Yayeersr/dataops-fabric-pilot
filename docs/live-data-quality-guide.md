# Live Data Quality (GX) — Template & Usage Guide

คู่มือนี้สรุปวิธีทำ data quality check แบบ **live** (เช็คข้อมูลสดตรงบน Fabric ผ่าน Spark) ด้วย
[Great Expectations](https://greatexpectations.io/) (GX) — เป็นผลจากการทำ POC จริงใน section 14
Phase 7 ของ `DataOps-CICD-Workflow.md` (repo เอกสารแยก) พิสูจน์แล้วว่า GX check ที่ raise error
ใน Notebook Activity ทำให้ pipeline job report เป็น `Failed` จริง ใช้เป็น automated DQ gate ได้

## เมื่อไหร่ควรใช้ live check (คู่มือนี้) เทียบกับ CSV/snapshot

| | Live check (คู่มือนี้) | CSV/snapshot (`data_quality` pattern เดิม) |
|---|---|---|
| ข้อมูลที่เช็ค | ข้อมูลจริงบน Lakehouse/Warehouse ผ่าน Spark ตรงๆ | ไฟล์ CSV ที่ commit ไว้ใน repo |
| เหมาะกับ | ตาราง production จริง ไม่ว่าขนาดเท่าไหร่ | ตารางเล็กมากๆ (lookup/config) หรือทดสอบ mechanism เฉยๆ |
| ข้อมูลออกจาก Fabric ไหม | ไม่เลย | ต้องดึงออกมาเป็นไฟล์ก่อน |
| **ใช้กับข้อมูลจริง/production** | ✅ ใช้ทางนี้เป็นหลัก | ❌ ไม่แนะนำ (ทีมตัดสินใจแล้วว่าจะไม่ใช้วิธี snapshot กับข้อมูลจริง) |

> ⚠️ **หมายเหตุสถานะปัจจุบัน**: กลไก CSV/snapshot (`scripts/run_data_quality_checkpoint.py`,
> `great_expectations/checkpoints/dq_TEMPLATE.yml`, self-test pair) ตอนนี้อยู่แค่ใน branch
> `test/data-quality-selftest` **ยังไม่ได้ merge เข้า `dev`/`main`** — บน `dev`/`main` จริง
> `great_expectations/checkpoints/` ยังว่างเปล่า (มีแค่ `.gitkeep`) แม้ `README.md` จะยังพูดถึง
> `dq_<name>.yml` เป็นไฟล์ "ขาดไม่ได้" อยู่ก็ตาม — ถ้าจะใช้แนวทางนั้นจริงต้อง merge branch นั้นก่อน
> คู่มือนี้พูดถึงเฉพาะแนวทาง live check เท่านั้น

## Architecture

เทมเพลตนี้ใช้ได้กับ **item ประเภทไหนก็ได้** ที่ Fabric รันเป็น "job" ได้ (Notebook, Data Pipeline)
และดึงข้อมูลได้ยังไงก็ได้ (Lakehouse ผ่าน Spark, Warehouse ผ่าน SQL) — เลือกเองได้ 2 จุด ตามตาราง
ด้านล่าง "จุดที่ต้องเลือกเอง"

```
ข้อมูลจริง (Lakehouse หรือ Warehouse)
        ↓
Notebook: โหลดข้อมูล → เช็คด้วย GX → raise ถ้า fail          ← เทมเพลตด้านล่าง ใช้ตัวเดียวกันเสมอ
        ↓ ถูกเรียกจาก (เลือกได้ 2 แบบ)
  แบบ A: Pipeline ห่อด้วย Notebook Activity                   ← ต้องมี parameter _inlineInstallationEnabled: true
  แบบ B: รัน Notebook ตรงๆ ไม่ผ่าน Pipeline
        ↑ สั่งรัน + รอผลโดย
scripts/run_live_dq_gate.py --item-type pipeline|notebook (เรียก Fabric REST API)
        ↑ ถูกเรียกโดย
CI job (เช่น dq-gate-poc ใน fabric-ci.yml — ปัจจุบัน manual trigger เท่านั้น)
```

**จุดที่ต้องเลือกเอง (user กำหนดตาม item จริง):**

| จุดที่เลือก | ตัวเลือก | เลือกยังไง |
|---|---|---|
| แหล่งข้อมูล | Lakehouse (Spark) / Warehouse (SQL) | ดูหัวข้อ "โหลดข้อมูลจากแหล่งไหน" ในเทมเพลตด้านล่าง |
| ตัวเรียกรัน | Pipeline ห่อ Notebook / Notebook ตรงๆ | ถ้าไม่มี activity อื่นต้องต่อ ใช้ Notebook ตรงๆ ง่ายกว่า (ข้าม parameter `_inlineInstallationEnabled` ได้ด้วย เพราะข้อจำกัดนั้นเกิดเฉพาะตอนถูกเรียกผ่าน pipeline — ยังไม่เคย verify จริง ลองแล้วบันทึกผลกลับมาด้วย) |
| `--item-type` ใน `run_live_dq_gate.py` | `pipeline` (default) / `notebook` | ให้ตรงกับตัวเรียกรันที่เลือกไว้แถวบน |

ดูตัวอย่างที่ implement จริงและพิสูจน์แล้ว (แบบ A, Lakehouse) ได้ที่ `fabric_items/nb_dqgate_check.Notebook/`,
`fabric_items/pl_dqgate_test.DataPipeline/`, `scripts/run_live_dq_gate.py`

## แยกโน้ตบุ๊คใหม่ทำ DQ โดยเฉพาะ หรือฝังเข้าโน้ตบุ๊ค transform เดิม?

ต้องมี "โน้ตบุ๊ค" (หรือ item ที่รัน Python/Spark ได้) เสมอ เพราะ GX ต้องมีที่รันโค้ด — แต่**ไม่จำเป็น
ต้องเป็นโน้ตบุ๊คใหม่แยกต่างหากเสมอไป** เลือกได้ 2 แบบ:

| | แยกโน้ตบุ๊คใหม่ (แบบที่ POC ทำ) | ฝังเข้าโน้ตบุ๊ค transform เดิม |
|---|---|---|
| เหมาะกับ | ตารางที่ไม่มี transform notebook เป็นเจ้าของชัดเจน (หลาย process เขียนเข้าตารางเดียวกัน) หรืออยากเรียกเช็คแยกได้เองโดยไม่ต้องรัน transform ใหม่ | มี transform notebook อยู่แล้ว อยากให้ "transform แล้วเช็คทันที" เป็น step เดียวกัน |
| Item ที่ต้องสร้างเพิ่ม | Notebook ใหม่ (+ Pipeline ใหม่ถ้าเลือกแบบ A) | ไม่ต้องสร้างอะไรเพิ่มเลย |
| การต่อสาย Pipeline | ต้องเพิ่ม Notebook Activity ใหม่ | ใช้ Notebook Activity เดิมที่เรียก transform notebook อยู่แล้ว (แค่เพิ่ม `_inlineInstallationEnabled` ถ้ายังไม่มี) |

### ตัวอย่างแบบฝังเข้าโน้ตบุ๊คเดิม

อ้างอิงจาก `fabric_items/yayee/nb_yayee_sales_transform.Notebook/notebook-content.py` (ตัวอย่าง
เท่านั้น ไม่ได้แก้ไฟล์จริง) — โค้ด transform เดิมท้ายไฟล์เขียนตารางแล้วจบแค่นี้:

```python
df = df.withColumn("region", when(col("product_id").isin("P001"), "BKK").otherwise("CNX"))

(df.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .save(table_path))

print(f"Done. Wrote to '{table_path}'.")
```

เพิ่ม cell ต่อท้ายตรงนี้เข้าไปในโน้ตบุ๊คเดียวกันเลย ไม่ต้องสร้างไฟล์ใหม่:

```python
# ── DQ check — เพิ่มต่อท้าย transform เดิม (ใช้ table_path ตัวแปรเดียวกับด้านบน) ──
%pip install "great_expectations>=1.0,<2.0"

import great_expectations as gx

df_check = spark.read.format("delta").load(table_path).toPandas()

_ge_context = gx.get_context(mode="ephemeral")
_ge_batch_definition = (
    _ge_context.data_sources.add_pandas("pandas")
    .add_dataframe_asset(name="sales_dq")
    .add_batch_definition_whole_dataframe("batch")
)
_batch = _ge_batch_definition.get_batch(batch_parameters={"dataframe": df_check})

expectations = [
    gx.expectations.ExpectColumnValuesToNotBeNull(column="product_id"),
    gx.expectations.ExpectColumnValuesToBeInSet(column="region", value_set=["BKK", "CNX"]),
]

results = [_batch.validate(e) for e in expectations]
all_passed = all(r.success for r in results)

for expectation, result in zip(expectations, results):
    status = "PASS" if result.success else "FAIL"
    print(f"[{status}] {expectation}")

if not all_passed:
    raise AssertionError("Data quality check failed after transform — ดูรายละเอียดที่ log ด้านบน")
```

จุดสำคัญที่ต่างจากแบบแยกโน้ตบุ๊ค:
- ใช้ตัวแปร `table_path` ที่ transform ประกาศไว้แล้ว ไม่ต้อง hardcode path ใหม่
- อ่านข้อมูล**กลับจากตารางที่เพิ่งเขียนเสร็จ** (`spark.read...load(table_path)`) ไม่ใช่ `df` ที่ยัง
  อยู่ใน memory ตรงๆ — ยืนยันว่าสิ่งที่ persist ลง Delta table จริงถูกต้อง (กันเคส write fail บางส่วน)
- ถ้า Notebook Activity เดิมยังไม่มี parameter `_inlineInstallationEnabled: true` ต้องเพิ่มด้วย
  (กฎเดียวกับหัวข้อ "ขั้นตอนตั้งค่าให้ item ใหม่" ด้านล่าง)

## ขั้นตอนตั้งค่าให้ item ใหม่

1. **สร้าง item ผ่าน Fabric UI ก่อนเสมอ** (Notebook เสมอ + Pipeline ถ้าเลือกแบบ A) — ห้าม
   hand-write ไฟล์ item ตรงเข้า `fabric_items/` (Fabric จะสร้าง `logicalId` เองตอน commit ผ่าน UI
   ถ้า hand-write เอง จะไม่ตรงกัน ทำให้ Git sync conflict — กฎนี้ verify มาแล้วจริงจาก section 14
   findings)

2. **copy เทมเพลตด้านล่างไปวางในโน้ตบุ๊ค** แล้วแก้ให้ตรงกับแหล่งข้อมูล/table/column/กฎของ item จริง

3. **ถ้าใช้ Lakehouse**: Attach Lakehouse เป็น default lakehouse ของโน้ตบุ๊ค (เมนู lakehouse ใน
   notebook UI) — **ถ้าใช้ Warehouse**: ตั้งค่า SQL connection ตามที่เทมเพลตต้องการแทน

4. **เลือกตัวเรียกรัน — แบบ A (ผ่าน Pipeline) หรือ แบบ B (Notebook ตรงๆ)**:

   **แบบ A** — เพิ่ม Notebook Activity ใน Pipeline ให้เรียกโน้ตบุ๊คนี้ → เปิด **Settings** ของ
   activity → **Base parameters** → เพิ่ม:
   - Name: `_inlineInstallationEnabled`, Type: `Boolean`, Value: `true`

   ⚠️ ขาดไม่ได้สำหรับแบบ A — Fabric ปิด `%pip install` ไว้โดย default สำหรับ notebook ที่ถูกเรียก
   ผ่าน pipeline (ป้องกัน dependency tree ไม่คงที่ระหว่าง run) ยืนยันจริงจากการเจอ
   `MagicUsageError: %pip magic command is disabled` ตอนทำ POC — parameter นี้คือ escape hatch
   ที่ Microsoft ให้มาอย่างเป็นทางการ ([อ้างอิง](https://learn.microsoft.com/en-us/fabric/data-engineering/library-management#inline-installation))

   **แบบ B** — ไม่ต้องสร้าง Pipeline เลย เหมาะกับ item ที่ไม่มี activity อื่นต้องต่อ (เช่น ไม่ต้อง
   trigger งานอื่นก่อน/หลังเช็ค) ข้อจำกัดเรื่อง `%pip` ข้างบนระบุไว้เฉพาะ **"pipeline runs"**
   เท่านั้น — เป็นไปได้ว่าแบบ B จะไม่ติดปัญหานี้เลย แต่ **ยังไม่เคย verify จริง** ในรีโปนี้ ถ้าลองแล้ว
   ช่วยบันทึกผลกลับมาไว้ในคู่มือนี้ด้วย

5. **Commit ผ่าน Fabric Studio → Source Control** ให้ sync เข้า `fabric_items/` ในรีโปนี้

6. **เพิ่ม entry ใน `ci-config.yml`** ให้ item ใหม่เป็น `skip_check: true` พร้อม `skip_reason`
   ที่ระบุว่าเช็คผ่าน live gate แทน ไม่ใช่ static definition check (ดูตัวอย่างที่ entry
   `nb_dqgate_check`/`pl_dqgate_test`/`lh_dqgate_test` ใน `ci-config.yml`)

7. **สั่งให้ CI รัน** ด้วย `scripts/run_live_dq_gate.py --workspace <GUID> --item-type <pipeline|notebook> --item-name <ชื่อ item>`
   — ให้ `--item-type` ตรงกับที่เลือกไว้ในข้อ 4 สคริปต์รองรับทั้ง 2 แบบอยู่แล้ว ไม่ต้องแก้โค้ด

   ถ้ามี item ที่ต้องเช็คแบบนี้**หลายตัวพร้อมกัน** (ยังไม่เคยต้องทำจริง ณ ตอนเขียนคู่มือนี้) แนวทางที่
   วางแผนไว้คือทำ config file แยก (เช่น `live-dq-gates.yml` คล้าย `endpoint-targets.yml`) ที่ list
   `item_type` + `item_name` + `workspace_id` ต่อแถว แล้วแก้ CI ให้วน loop เรียก
   `run_live_dq_gate.py` ทีละแถว สะสม error ท้ายสุด — **อย่าเพิ่งสร้างกลไกนี้จนกว่าจะมี item ตัวที่ 2
   จริงๆ** (ไม่งั้นจะกลายเป็น over-engineer ก่อนรู้ requirement จริง)

## เทมเพลตทั้งหมด (copy ไปแก้ต่อได้เลย)

รวมเทมเพลตของทุกไฟล์ที่ต้องแตะเวลาตั้งค่า item ใหม่ 1 ตัว — เรียงตามลำดับที่ใช้จริงในขั้นตอนด้านบน

### 1. Notebook (`notebook-content.py`) — โค้ดหลักที่ต้องเขียน

โครงสร้างอิงตาม 7 มิติมาตรฐานเดียวกับ `great_expectations/checkpoints/dq_TEMPLATE.yml`
(Completeness / Uniqueness / Validity / Accuracy / Consistency / Timeliness / Integrity) —
**อย่า copy ทั้งดุ้น** ตัดเหลือแค่มิติที่ item จริงต้องเช็ค แล้วเติมค่าจาก business rule จริง

```python
# ── ตั้งค่า ────────────────────────────────────────────────────────────
TABLE_NAME = "<ชื่อตาราง เช่น dqgate_sample>"

# ── ติดตั้ง GX (จำเป็นเสมอ — ไม่ preinstall มากับ Fabric runtime) ──────
%pip install "great_expectations>=1.0,<2.0"

# ── โหลดข้อมูลจากแหล่งไหน — เลือก 1 อันตามชนิด item ที่เช็ค ────────────
import great_expectations as gx

# ตัวเลือก A: Lakehouse (Spark) — attach lakehouse เป็น default lakehouse ของ notebook ก่อน
df = spark.table(TABLE_NAME).toPandas()

# ตัวเลือก B: Warehouse (SQL) — ใช้แทนบรรทัดบนถ้า item เป็น Warehouse ไม่ใช่ Lakehouse
# df = spark.read.option("url", "<connection string ของ Warehouse>") \
#     .option("dbtable", TABLE_NAME).format("com.microsoft.sqlserver.jdbc.spark") \
#     .load().toPandas()
# (หรือรัน T-SQL cell แยกแล้วส่ง DataFrame ที่ได้เข้าตัวแปร df แทนก็ได้ ขึ้นกับรูปแบบที่ทีมถนัด)

# ── เตรียม batch สำหรับ validate ──────────────────────────────────────
_ge_context = gx.get_context(mode="ephemeral")
_ge_batch_definition = (
    _ge_context.data_sources.add_pandas("pandas")
    .add_dataframe_asset(name="dq_check")
    .add_batch_definition_whole_dataframe("batch")
)
_batch = _ge_batch_definition.get_batch(batch_parameters={"dataframe": df})

# ── ประกาศ expectation ที่ต้องเช็ค (ตัดมิติที่ไม่เกี่ยวออก) ────────────
expectations = [
    # 1. Completeness — ห้าม column สำคัญว่าง
    gx.expectations.ExpectColumnValuesToNotBeNull(column="<ชื่อ column>"),

    # 2. Uniqueness — ห้าม key ซ้ำ
    # gx.expectations.ExpectColumnValuesToBeUnique(column="<ชื่อ column key>"),

    # 3. Validity — ค่าต้องอยู่ในช่วง/รูปแบบที่กำหนด
    # gx.expectations.ExpectColumnValuesToBeBetween(column="<column>", min_value=0, max_value=100),
    # gx.expectations.ExpectColumnValuesToMatchRegex(column="<column>", regex="^0[0-9]{9}$"),

    # 4. Accuracy — ค่า 2 column ต้องสอดคล้องกัน (GX เช็คตรงๆ ให้ไม่ได้ ทำได้แค่ประมาณแบบนี้)
    # gx.expectations.ExpectColumnPairValuesAToBeGreaterThanB(column_A="<a>", column_B="<b>", or_equal=True),

    # 5. Consistency — ค่าต้องอยู่ในชุดที่ตกลงกันไว้
    # gx.expectations.ExpectColumnValuesToBeInSet(column="<column>", value_set=["new", "qualified"]),

    # 6. Timeliness — เช็คว่าค่า max ของ column วันที่อยู่ในช่วงที่ยอมรับได้
    # gx.expectations.ExpectColumnMaxToBeBetween(column="<column>", min_value="2026-01-01", max_value="2026-12-31"),

    # 7. Integrity — referential integrity ข้ามตาราง GX เช็คแบบ live ตรงๆ ยังไม่รองรับในเทมเพลตนี้
    # ต้อง query ตารางแม่มาก่อนแล้วเทียบเอง (ดูหมายเหตุใน dq_TEMPLATE.yml ฝั่ง CSV)
]

# ── รันเช็คทุกกฎ + สรุปผล ──────────────────────────────────────────────
results = [_batch.validate(e) for e in expectations]
all_passed = all(r.success for r in results)

for expectation, result in zip(expectations, results):
    status = "PASS" if result.success else "FAIL"
    print(f"[{status}] {expectation}")

if not all_passed:
    raise AssertionError("Data quality check failed — ดูรายละเอียดที่ log ด้านบน")
```

**สิ่งที่ต้องแก้เสมอ**:
- `TABLE_NAME` และ column ทุกตัวใน `expectations`
- ลบ comment กฎที่ไม่เกี่ยวออก แล้ว uncomment กฎที่ต้องใช้จริง (threshold/regex/value_set ต้องมาจาก
  คนที่รู้ business rule ของ item นั้น เดาเองไม่ได้)
- **`raise AssertionError` ต้องอยู่** — นี่คือจุดที่ทำให้ pipeline job fail จริง ถ้าตัดออกกลไก gate
  จะไม่ทำงาน (เช็คแล้ว print ผลเฉยๆ ไม่พอ)

### 2. Pipeline Activity (`pipeline-content.json`) — ใช้เฉพาะแบบ A

⚠️ **ห้าม copy JSON นี้ไปวางไฟล์ตรงๆ** — สร้าง Notebook Activity ผ่าน Fabric UI เสมอ (กฎ UI-first
ข้อ 1 ด้านบน) ใช้ตรงนี้แค่เป็น**ตัวอ้างอิงเทียบผล** ว่าไฟล์ที่ sync เข้ามาหลัง commit ผ่าน UI แล้ว
ควรมีหน้าตาประมาณนี้ (โดยเฉพาะ parameter `_inlineInstallationEnabled` ที่ต้องมี):

```json
{
  "properties": {
    "activities": [
      {
        "type": "TridentNotebook",
        "typeProperties": {
          "notebookId": "<GUID ของ notebook ที่สร้างไว้ในข้อ 1 — Fabric ใส่ให้เองหลัง sync>",
          "workspaceId": "00000000-0000-0000-0000-000000000000",
          "parameters": {
            "_inlineInstallationEnabled": {
              "value": true,
              "type": "bool"
            }
          }
        },
        "policy": {
          "timeout": "0.12:00:00",
          "retry": 0,
          "retryIntervalInSeconds": 30,
          "secureInput": false,
          "secureOutput": false
        },
        "name": "<ชื่อ activity ที่ตั้งใน UI>",
        "dependsOn": []
      }
    ]
  }
}
```

ถ้า sync เข้ามาแล้วไม่มี key `parameters`/`_inlineInstallationEnabled` แปลว่าลืมตั้งค่า Base
parameter ในข้อ 4 (แบบ A) — กลับไปเพิ่มผ่าน UI แล้ว commit ใหม่

### 3. `ci-config.yml` — entry ให้ item ใหม่

เพิ่มต่อท้ายไฟล์ (1 entry ต่อ item ที่ sync เข้ามา — Notebook + Pipeline ถ้าใช้แบบ A, Lakehouse
ถ้ามี table ทดสอบที่ไม่มี schema contract จริงให้เช็ค):

```yaml
<ชื่อ_notebook_item>:
  skip_check: true
  skip_reason: >-
    Live DQ check item (<วันที่ตั้งค่า>) — เช็คผ่าน live gate (scripts/run_live_dq_gate.py)
    แทน ไม่ใช่ static definition check ดู docs/live-data-quality-guide.md

<ชื่อ_pipeline_item>:   # ตัดออกถ้าใช้แบบ B (ไม่มี pipeline)
  skip_check: true
  skip_reason: >-
    Live DQ check item (<วันที่ตั้งค่า>) คู่กับ <ชื่อ_notebook_item> — ดูเหตุผลเดียวกัน

<ชื่อ_lakehouse_item>:   # ตัดออกถ้าไม่มี table ทดสอบใหม่ หรือมี schema contract จริงให้เช็คแล้ว
  skip_check: true
  skip_reason: >-
    Live DQ check item (<วันที่ตั้งค่า>) — ไม่มี schema contract จริงให้เช็คตอนนี้
```

### 4. `.github/workflows/fabric-ci.yml` — job สั่งรัน CI ให้ item ใหม่

เพิ่มเป็น job ใหม่ต่อท้ายไฟล์ (คนละ item ก็คนละ job — จะรวมเป็น job เดียวก็ได้ถ้ามีหลาย item แล้ว
อยากลดโค้ดซ้ำ แต่ดูหัวข้อ "ถ้ามี item หลายตัว" ด้านบนก่อนว่ายังไม่แนะนำให้ทำตอนนี้):

```yaml
  dq-gate-<ชื่อสั้นๆของ item>:
    if: github.event_name == 'workflow_dispatch'   # เปลี่ยนเป็น auto-trigger ทีหลังได้เมื่อ verify ครบแล้ว
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - name: Run live DQ gate against <ชื่อ_item>
        run: python scripts/run_live_dq_gate.py --workspace <workspace GUID> --item-type <pipeline หรือ notebook> --item-name <ชื่อ_item>
        env:
          FABRIC_CLIENT_ID: ${{ secrets.FABRIC_CLIENT_ID }}
          FABRIC_CLIENT_SECRET: ${{ secrets.FABRIC_CLIENT_SECRET }}
          FABRIC_TENANT_ID: ${{ secrets.FABRIC_TENANT_ID }}
```

`--item-type`/`--item-name` ต้องตรงกับตัวเรียกรันที่เลือกไว้ในข้อ 4 ของขั้นตอนตั้งค่า (แบบ A ใส่
`pipeline` + ชื่อ pipeline, แบบ B ใส่ `notebook` + ชื่อ notebook โดยตรง)

**พอ verify ผ่านครบทั้งเคส good/bad data แล้ว** เปลี่ยนจาก manual-only เป็น auto-trigger ตอน push
เข้า `main` ได้ (ดูตัวอย่างจริงที่ job `dq-gate-poc` ใน `fabric-ci.yml`) — 2 จุดที่ต้องระวัง:
- ให้รันหลัง `deploy-prod` เสร็จเสมอ (`needs: deploy-prod`) เพราะต้องเช็คของที่เพิ่ง deploy ขึ้น
  prod จริง ไม่ใช่ของเดิมใน dev
- ใช้ `if: always() && (github.event_name == 'workflow_dispatch' || (... && needs.deploy-prod.result == 'success'))`
  แทนแค่ `needs: deploy-prod` เฉยๆ — เพราะ `deploy-prod` เองมี `if` ที่ skip ได้ (เช่นตอน trigger
  แบบ manual) ถ้าไม่เช็ค `result` แบบนี้ job นี้จะโดน skip ตามไปด้วย ทำให้กดรันมือไม่ได้อีกเลย
- อย่าลืมเปลี่ยน workspace GUID ในคำสั่งจาก dev เป็น prod ด้วย ไม่งั้นจะเช็คผิด environment

## เลือก GX expectation ได้จากไหนบ้าง

ไม่ได้จำกัดแค่ตัวอย่างในเทมเพลตด้านบน — GX มี built-in expectation ให้เลือกเป็นร้อยตัว ดูรายชื่อ
เต็มได้ที่ https://greatexpectations.io/expectations/ ชื่อใน Python ใช้ PascalCase (เช่น
`ExpectColumnValuesToBeOfType`) ตรงกับ class ใน `gx.expectations`

## ถ้ากฎที่ต้องการไม่มี built-in ให้เลย — เขียนกฎเอง

มี 2 ทาง เลือกตามความซับซ้อนของกฎ:

### ทางที่ 1 (แนะนำ) — เขียน check function ธรรมดา ไม่ต้องพึ่ง GX framework

เหมาะกับ**เกือบทุกกรณีที่เจอจริง** — เขียนฟังก์ชัน Python/pandas เช็คเงื่อนไขเอง แล้วเอาผลไป
เข้า flow เดียวกับ GX expectation (print `[PASS]`/`[FAIL]` + นับรวมกับ `all_passed`) ไม่ต้องแตะ
internal API ของ GX เลย ความเสี่ยง syntax ผิดเกือบเป็นศูนย์เพราะเป็นแค่ pandas ธรรมดา:

```python
# ตัวอย่าง custom rule: "ยอดขายต่อวันห้ามเกิน 3 เท่าของค่าเฉลี่ย 7 วันย้อนหลัง" (ไม่มี built-in ตรงๆ)
def check_no_sales_spike(pdf, column="sales_amount", window=7, max_multiplier=3):
    rolling_avg = pdf[column].rolling(window=window, min_periods=1).mean()
    violations = pdf[pdf[column] > rolling_avg * max_multiplier]
    return len(violations) == 0, violations

custom_passed, violation_rows = check_no_sales_spike(df)
print(f"[{'PASS' if custom_passed else 'FAIL'}] check_no_sales_spike ({len(violation_rows)} แถวผิดปกติ)")
all_passed = all_passed and custom_passed   # รวมเข้ากับผลของ GX expectations ด้านบน
```

วางต่อท้าย loop `for expectation, result in zip(...)` ในเทมเพลตได้เลย แล้วให้ `all_passed` ตัวเดียว
คุม `raise AssertionError` ทั้งหมด (ทั้งจาก GX expectation และจาก custom check)

### ทางที่ 2 — เขียนเป็น GX Custom Expectation class จริงๆ

เหมาะถ้าอยากได้กฎที่ reuse ข้ามหลาย notebook/item ในรูปแบบเดียวกับ built-in (เรียกผ่าน
`gx.expectations.<ชื่อกฎ>(...)` เหมือนกฎอื่น) — รูปแบบที่ GX เอกสารไว้ (subclass
`ColumnMapExpectation` + `ColumnMapMetricProvider`):

```python
from great_expectations.expectations.expectation import ColumnMapExpectation
from great_expectations.expectations.metrics.map_metric_provider import (
    ColumnMapMetricProvider,
    column_condition_partial,
)
from great_expectations.execution_engine import PandasExecutionEngine

class ColumnValuesToBeEven(ColumnMapMetricProvider):
    condition_metric_name = "column_values.even"

    @column_condition_partial(engine=PandasExecutionEngine)
    def _pandas(cls, column, **kwargs):
        return column % 2 == 0

class ExpectColumnValuesToBeEven(ColumnMapExpectation):
    map_metric = "column_values.even"
    success_keys = ("mostly",)
```

⚠️ **ยังไม่เคย verify จริงกับ GX เวอร์ชันที่ pin ไว้ในรีโปนี้ (`great_expectations>=1.0,<2.0`)** —
import path พวกนี้เป็นรูปแบบที่ GX เอกสารไว้สาธารณะ แต่รีโปนี้เคยเจอมาแล้วว่า docs กับ source code
ของเวอร์ชันที่ติดตั้งจริงไม่ตรงกันได้ (เช่นเคสของ `fabric-cicd` parameter.yml ใน section 14
findings) — **ก่อนใช้จริงให้เช็ค `python -c "import great_expectations; help(great_expectations.expectations.expectation)"`
กับเวอร์ชันที่ติดตั้งจริงก่อนเสมอ** อย่าเชื่อ syntax นี้เปล่าๆ

โดยรวม **แนะนำทางที่ 1** สำหรับรีโปนี้ เพราะเรียบง่ายกว่า verify ง่ายกว่า และครอบคลุม use case ที่
เจอจริงได้หมดโดยไม่ต้องพึ่งความเข้าใจ internal ของ GX เลย

## ปัญหาที่เจอจริงระหว่างทำ POC (และวิธีแก้)

รายละเอียดเต็มอยู่ใน `DataOps-CICD-Workflow.md` section 14 Phase 7 สรุปสั้นๆ ที่ต้องรู้ก่อนเริ่ม:

| ปัญหา | วิธีแก้ |
|---|---|
| `ModuleNotFoundError: No module named 'great_expectations'` | ไม่ preinstall มากับ Fabric runtime — ต้อง `%pip install` เสมอ (มีอยู่ในเทมเพลตแล้ว) |
| `MagicUsageError: %pip magic command is disabled` ตอนรันผ่าน Pipeline | ต้องเพิ่ม parameter `_inlineInstallationEnabled: true` ที่ Notebook Activity (ดูขั้นตอนที่ 4 ด้านบน) — ห้ามลืม |
| อยากใช้ Fabric Environment แทน `%pip` (ให้ reproducible กว่า) | ลองแล้วในเทนแนนต์นี้ UI "Custom libraries" ของ Environment item มีแค่ upload .whl/.jar/.tar.gz ไม่มีช่องพิมพ์ชื่อ public package ตรงๆ ทั้ง All/Full mode — ยังไม่มีทางทำได้ง่ายๆ ในตอนนี้ ใช้ `_inlineInstallationEnabled` ไปก่อน |

## วิธีตรวจว่าเช็คผ่านไหม

- **ดูตรงจาก Fabric**: Monitoring Hub → run ของ pipeline → สถานะ `Succeeded`/`Failed` + เปิด log
  ของ Notebook Activity ดูบรรทัด `[PASS]`/`[FAIL]` ต่อกฎ
- **ดูผ่าน CI** (ถ้าต่อ `run_live_dq_gate.py` ไว้): job status เขียว/แดงตรงกับผลจริง, log มี JSON
  เต็มของ job instance + บรรทัดสรุปว่า "live data_quality gate ผ่าน" หรือ `::error::...`

ทดสอบทั้ง 2 เคสเสมอก่อนถือว่า item พร้อมใช้จริง: ข้อมูลดี → ต้อง `Succeeded`, ทำข้อมูลเสีย 1 แถว
ชั่วคราว (เช่น `UPDATE table SET col = NULL WHERE id = X`) → รันซ้ำ → ต้อง `Failed` จริง ก่อนคืนค่า
ข้อมูลกลับ

## ไฟล์ที่เกี่ยวข้องทั้งหมด (ตัวอย่างจาก POC)

| ไฟล์ | หน้าที่ |
|---|---|
| `fabric_items/lh_dqgate_test.Lakehouse/` | Lakehouse ตัวอย่างเก็บตารางทดสอบ |
| `fabric_items/nb_dqgate_check.Notebook/notebook-content.py` | Notebook ตัวอย่าง (ต้นแบบของเทมเพลตด้านบน) |
| `fabric_items/pl_dqgate_test.DataPipeline/pipeline-content.json` | Pipeline ตัวอย่าง มี `_inlineInstallationEnabled` |
| `scripts/run_live_dq_gate.py` | สั่งรัน pipeline ผ่าน Fabric REST API + poll ผล + exit code |
| `ci-config.yml` | entry `skip_check` ตัวอย่างสำหรับ 3 item ข้างบน |
| `.github/workflows/fabric-ci.yml` | job `dq-gate-poc` เรียก `run_live_dq_gate.py` |
| `DataOps-CICD-Workflow.md` section 14 Phase 7 | findings log เต็มของ POC นี้ |
