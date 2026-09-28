"""
เรียกจาก fabric-ci.yml สำหรับ item type Lakehouse/Warehouse (check=schema)
เช็คว่ามี schema contract ไฟล์ประกาศไว้จริง (schema_contracts/<item_name>.yml) และ format ถูกต้อง

ข้อจำกัดที่ต้องรู้: Fabric Git Integration ไม่ sync ข้อมูล table/column schema ของ
Lakehouse/Warehouse มาให้เลย (ตรวจสอบแล้ว — Lakehouse item ที่ sync ลงมามีแค่ .platform,
alm.settings.json, lakehouse.metadata.json ที่เป็นแค่ {"defaultSchema": "dbo"}/{}, กับ
shortcuts.metadata.json — ไม่มี column ไหนอยู่ในนั้นเลย) แปลว่า script นี้เช็คได้แค่ "มี contract
ประกาศไว้ไหม + format ถูกไหม" เท่านั้น **ไม่ได้เช็คว่า contract ตรงกับ schema จริงบน Fabric**
เพราะไม่มีอะไรให้ diff เทียบเลย ถ้าต้องการเช็คกับของจริง ต้องทำเป็น live check แยกต่างหาก
(pattern เดียวกับ scripts/run_live_dq_gate.py — Notebook อ่าน schema จริงมาเทียบ) ซึ่งรันก่อน
deploy ไม่ได้เหมือน 5 pattern เดิม (ดูเหตุผลใน CLAUDE.md ของ repo เอกสารแยก)

รูปแบบ contract (schema_contracts/<item_name>.yml — ชื่อไฟล์ต้องตรงชื่อ item เป๊ะ เหมือน
pattern ของ tests/unit/test_<name>.py และ great_expectations/checkpoints/dq_<name>.yml):
    tables:
      <table_name>:
        columns:
          - name: <column_name>
            type: <string|int|bigint|double|float|boolean|date|timestamp>
"""
import os
import sys

import yaml

VALID_TYPES = {"string", "int", "bigint", "double", "float", "boolean", "date", "timestamp"}


def _find_repo_root(item_path: str) -> str:
    # หา repo root โดยไต่ขึ้นจนเจอโฟลเดอร์ชื่อ "fabric_items" แล้วขึ้นอีก 1 ชั้น — เหมือน
    # scripts/validate_pipeline_structure.py เพราะ item อาจอยู่ใต้ Fabric workspace folder ได้
    path = os.path.abspath(item_path)
    while True:
        parent, name = os.path.split(path)
        if name == "fabric_items":
            return parent
        if parent == path:
            raise RuntimeError(f"could not locate 'fabric_items' ancestor of {item_path}")
        path = parent


def _item_name(item_path: str) -> str:
    folder = os.path.basename(item_path.rstrip("/"))
    return folder.rsplit(".", 1)[0]


def validate(item_path: str) -> bool:
    name = _item_name(item_path)
    repo_root = _find_repo_root(item_path)
    contract_path = os.path.join(repo_root, "schema_contracts", f"{name}.yml")

    if not os.path.isfile(contract_path):
        print(f"[validate_schema_contract] {item_path}: ไม่พบ schema contract ({contract_path})")
        return False

    with open(contract_path, encoding="utf-8") as f:
        contract = yaml.safe_load(f) or {}

    tables = contract.get("tables")
    if not tables or not isinstance(tables, dict):
        print(f"[validate_schema_contract] {contract_path}: ไม่มี key 'tables' หรือว่างเปล่า")
        return False

    ok = True
    for table_name, table_def in tables.items():
        columns = (table_def or {}).get("columns")
        if not columns:
            print(f"[validate_schema_contract] {contract_path}: table '{table_name}' ไม่มี column ประกาศไว้เลย")
            ok = False
            continue

        for col in columns:
            col_name = col.get("name")
            col_type = col.get("type")
            if not col_name:
                print(f"[validate_schema_contract] {contract_path}: table '{table_name}' มี column ที่ไม่มี 'name'")
                ok = False
                continue
            if col_type not in VALID_TYPES:
                print(
                    f"[validate_schema_contract] {contract_path}: table '{table_name}'.{col_name} "
                    f"type '{col_type}' ไม่รู้จัก (ต้องเป็นหนึ่งใน {sorted(VALID_TYPES)})"
                )
                ok = False
            else:
                print(f"[validate_schema_contract] {contract_path}: table '{table_name}'.{col_name} ({col_type}) OK")

    if ok:
        print(f"[validate_schema_contract] {contract_path}: ผ่าน ({len(tables)} table)")
    return ok


if __name__ == "__main__":
    item_path = sys.argv[1]
    if not validate(item_path):
        sys.exit(1)
