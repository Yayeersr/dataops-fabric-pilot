"""
สร้าง unit test stub ให้ notebook lab ของผู้เข้าอบรมแต่ละคน (pattern: nb_<ชื่อ>_lab)

ทำไมต้องมี script นี้: ชื่อไฟล์ test ต้องตรงชื่อ item เป๊ะ (tests/unit/test_<name>.py) ถ้าพิมพ์ผิด
CI จะหาไฟล์ test ไม่เจอแล้ว error ทันที (ดู README ข้อจำกัดข้อ 2) — script นี้เช็คว่า item มีจริง
ใน fabric_items/ ก่อน แล้วค่อยสร้างไฟล์ test ให้ชื่อตรงกันเป๊ะ ลดจุดพิมพ์ผิด

Precondition: ต้องสร้าง Notebook ผ่าน Fabric UI แล้วกด Commit ผ่าน Source Control panel ก่อน
(sync เข้า fabric_items/) ถึงจะรัน script นี้ได้ — script นี้ไม่สร้าง item ให้ (ขัดกฎ "สร้าง item
ผ่าน Fabric UI เท่านั้น" ของ repo นี้)

รัน:
    python scripts/new_lab.py <ชื่อ>   เช่น python scripts/new_lab.py natcha
"""

import argparse
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(BASE_DIR, "..")
FABRIC_ITEMS_DIR = os.path.join(REPO_ROOT, "fabric_items")
TESTS_DIR = os.path.join(REPO_ROOT, "tests", "unit")

TEST_TEMPLATE = '''"""
Dry-run test สำหรับ {item_name} — สร้างโดย scripts/new_lab.py
แก้ test_placeholder() ด้านล่างให้เช็ค logic จริงของ notebook นี้
"""


def test_placeholder():
    assert True
'''


def _find_item_dir(item_name: str):
    # หา item folder แบบ recursive เผื่ออยู่ใต้ Fabric workspace folder (เช่นเดียวกับที่
    # fabric-ci.yml หา .platform แบบ recursive ไม่ใช่แค่ fabric_items/*/ ระดับเดียว)
    target = f"{item_name}.Notebook"
    for dirpath, _dirnames, _filenames in os.walk(FABRIC_ITEMS_DIR):
        if os.path.basename(dirpath) == target and os.path.isfile(os.path.join(dirpath, ".platform")):
            return dirpath
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="ชื่อผู้เข้าอบรม (เช่น natcha) — item ต้องชื่อ nb_<ชื่อ>_lab")
    args = parser.parse_args()

    item_name = f"nb_{args.name}_lab"

    if _find_item_dir(item_name) is None:
        sys.exit(
            f"ไม่พบ {item_name}.Notebook ใน fabric_items/ — ต้องสร้าง Notebook ผ่าน Fabric UI "
            "แล้วกด Commit ผ่าน Source Control panel ก่อน (sync เข้า fabric_items/) ถึงจะรัน "
            "script นี้ได้"
        )

    os.makedirs(TESTS_DIR, exist_ok=True)
    test_path = os.path.join(TESTS_DIR, f"test_{item_name}.py")

    if os.path.isfile(test_path):
        sys.exit(f"มีไฟล์ {test_path} อยู่แล้ว — ไม่เขียนทับ (แก้ไฟล์นั้นตรงๆ ถ้าต้องการเปลี่ยน)")

    with open(test_path, "w", encoding="utf-8") as f:
        f.write(TEST_TEMPLATE.format(item_name=item_name))

    print(f"สร้าง {test_path} แล้ว — แก้ test_placeholder() ให้เช็ค logic จริงของ {item_name} ก่อน push")


if __name__ == "__main__":
    main()
