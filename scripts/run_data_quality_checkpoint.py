"""
รัน data_quality checkpoint จาก great_expectations/checkpoints/<name>.yml

ทำไมไม่ใช้ `great_expectations checkpoint run <name>` (CLI แบบเดิม) ตรงๆ:
    great_expectations ที่ pin ใน requirements.txt เป็น GX 1.x ("GX Core") ซึ่งตัด CLI +
    DataContext/checkpoint-yaml แบบ legacy (0.13-0.18) ออกหมดแล้ว — ไม่มีแม้แต่ subcommand
    `checkpoint` หรือ console script `great_expectations` ให้เรียกด้วยซ้ำ ต้องสร้าง
    ExpectationSuite/Checkpoint ผ่าน Python API แทน

    script นี้แปลง config yaml แบบง่ายๆ (data_file + expectations list) ให้เป็น GX 1.x object
    แล้วรันให้ — ตาม pattern เดียวกับ validate_pipeline_structure.py / validate_schema_contract.py
    (script กลางต่อ check pattern หนึ่งตัว ไม่ผูกกับ Fabric item type)

รูปแบบ config (great_expectations/checkpoints/dq_<name>.yml):
    data_file: path/to/sample.csv   # relative ต่อ repo root
    dtype:                          # optional — บังคับ dtype ต่อ column ตอนอ่าน CSV
      phone_number: str             # (ดู comment ข้อจำกัดด้านล่าง ทำไมต้องมีตัวนี้)
    expectations:
      - expectation_type: expect_column_values_to_not_be_null
        kwargs:
          column: customer_id

ข้อจำกัด: รองรับเฉพาะข้อมูลที่โหลดเป็น pandas DataFrame จากไฟล์ (CSV) ได้ — เหมาะกับ fixture
สำหรับทดสอบกลไก CI ระหว่าง training ไม่ใช่ตัวเชื่อมต่อ live Lakehouse/Warehouse จริง

⚠️ pandas เดา dtype ของแต่ละ column เองจาก CSV — column ที่ค่าเป็นตัวเลขล้วน (เช่น
เบอร์โทรที่ขึ้นต้นด้วย 0, รหัสไปรษณีย์) จะถูกอ่านเป็น int แล้ว "0812345678" กลายเป็น
812345678 (เลข 0 ข้างหน้าหายไปเงียบๆ) ทำให้ expect_column_values_to_match_regex ที่คาด
ว่าเป็น string fail ทั้งที่ข้อมูลจริงถูกต้อง — ถ้า column ไหนต้องคงความเป็น string
(โดยเฉพาะที่ขึ้นต้นด้วย 0 หรือใช้เช็ค regex) ให้ประกาศไว้ใน key `dtype:` ด้านบน

รัน:
    python scripts/run_data_quality_checkpoint.py dq_<name>
"""

import argparse
import os
import sys

import great_expectations as gx
import pandas as pd
import yaml

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(BASE_DIR, "..")
CHECKPOINTS_DIR = os.path.join(REPO_ROOT, "great_expectations", "checkpoints")


def _to_pascal_case(expectation_type: str) -> str:
    # รองรับทั้ง snake_case (expect_column_values_to_not_be_null, รูปแบบที่ GX ใช้เป็นชื่อ
    # "type" เวลา print ผล) และ PascalCase (ExpectColumnValuesToNotBeNull, ชื่อ class จริง
    # ใน gx.expectations) — เขียน config ด้วยแบบไหนก็ได้
    if "_" not in expectation_type:
        return expectation_type
    return "".join(part.capitalize() for part in expectation_type.split("_"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="ชื่อ checkpoint — ตรงกับไฟล์ great_expectations/checkpoints/<name>.yml")
    args = parser.parse_args()

    config_path = os.path.join(CHECKPOINTS_DIR, f"{args.name}.yml")
    if not os.path.isfile(config_path):
        sys.exit(f"::error::ไม่พบ checkpoint config: {config_path}")

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    data_file = config.get("data_file")
    if not data_file:
        sys.exit(f"::error::{config_path} ไม่มี key 'data_file'")

    data_path = os.path.join(REPO_ROOT, data_file)
    if not os.path.isfile(data_path):
        sys.exit(f"::error::ไม่พบไฟล์ข้อมูล: {data_path}")

    expectations = config.get("expectations") or []
    if not expectations:
        sys.exit(f"::error::{config_path} ไม่มี expectation ให้เช็คเลย (key 'expectations' ว่าง)")

    df = pd.read_csv(data_path, dtype=(config.get("dtype") or None))

    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas(f"{args.name}_source")
    data_asset = data_source.add_dataframe_asset(name=f"{args.name}_asset")
    batch_definition = data_asset.add_batch_definition_whole_dataframe(f"{args.name}_batch")

    suite = context.suites.add(gx.ExpectationSuite(name=f"{args.name}_suite"))
    for expectation in expectations:
        raw_type = expectation["expectation_type"]
        expectation_cls = getattr(gx.expectations, _to_pascal_case(raw_type), None)
        if expectation_cls is None:
            sys.exit(
                f"::error::ไม่รู้จัก expectation_type '{raw_type}' "
                "(ดูชื่อที่ถูกต้องได้ที่ https://greatexpectations.io/expectations/)"
            )
        suite.add_expectation(expectation_cls(**(expectation.get("kwargs") or {})))

    validation_definition = context.validation_definitions.add(
        gx.ValidationDefinition(name=f"{args.name}_validation", data=batch_definition, suite=suite)
    )
    checkpoint = context.checkpoints.add(
        gx.Checkpoint(name=f"{args.name}_checkpoint", validation_definitions=[validation_definition])
    )
    result = checkpoint.run(batch_parameters={"dataframe": df})

    for validation_result in result.run_results.values():
        for expectation_result in validation_result.results:
            status = "PASS" if expectation_result.success else "FAIL"
            kwargs = dict(expectation_result.expectation_config.kwargs)
            kwargs.pop("batch_id", None)
            print(f"[{status}] {expectation_result.expectation_config.type} {kwargs}")

    if not result.success:
        sys.exit(f"::error::data_quality checkpoint '{args.name}' fail — ดู expectation ที่ FAIL ด้านบน")

    print(f"data_quality checkpoint '{args.name}' passed")


if __name__ == "__main__":
    main()
