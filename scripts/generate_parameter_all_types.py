"""
Generate/update fabric_items/parameter.yml สำหรับ Fabric item "ทุก type" — ไม่ผูกกับ Notebook/DataPipeline

ต่างจาก generate_parameter.py ยังไง:
    generate_parameter.py อ่าน GUID จาก metadata เฉพาะที่ Fabric ฝังชื่อไว้คู่กัน (Notebook/DataPipeline)
    สคริปต์นี้ใช้วิธีกลับด้าน — ดึงรายการ item จริงของ Dev workspace (id + type + ชื่อ) จาก Fabric REST API
    แล้วสแกน "ทุกไฟล์" ในทุก item ใน repo หา GUID เหล่านั้น เลยไม่ต้องรู้ format ของแต่ละ item type
    (Notebook, DataPipeline, Dataflow, SemanticModel, Report, Warehouse, ... ใช้ logic เดียวกันหมด)

หลักการ:
    1. GET /v1/workspaces/{dev}/items -> {guid: (type, displayName)} + workspace id ของ Dev เอง
    2. สแกนทุกไฟล์ text ใน item folder (ข้าม .platform) หา GUID ของ item/workspace ใน Dev ตามที่เขียนไว้ตรงๆ
    3. เจอ GUID ที่ตรงกับ item ใน Dev -> เขียน find_replace entry:
         find_value   = สตริงตามที่เจอในไฟล์จริง (คง format/ตัวพิมพ์เดิม)
         replace_value= {_ALL_: "$items.<Type>.<name>.$id"} หรือ "$workspace.$id"
         item_type    = type ของ item ที่ไฟล์นั้นอยู่ (ไม่ใช่ type ของ item ที่ถูกอ้างถึง)
    4. GUID ที่ตรงกับ logicalId ใน .platform ของ item ใน repo -> ไม่สร้าง entry: fabric-cicd แทน logicalId
       เป็น id จริงของ target ให้เองตอน publish อยู่แล้ว (ยืนยันจาก pl_dqgate_test: notebookId = logicalId
       ของ nb_dqgate_check และ prod ชี้ notebook ของ prod ถูกต้องโดยไม่มี rule) แค่รายงานไว้เฉยๆ
       — logicalId ของ item ที่สร้างผ่าน UI หน้าตาเหมือน id จริงของ Dev ที่ถูกสลับบล็อก จึงห้ามเอา
       "สลับบล็อก" มาเดาเป็น id ของ Dev (เคยทำแล้วได้ rule ซ้ำซ้อน)
    5. GUID อื่นที่ไม่ตรงกับ item ใน Dev หรือ logicalId (เช่น external Connection ID, item ข้าม workspace)
       -> แค่เตือน ไม่เดาให้ ต้องกรอกเอง

ข้อจำกัด:
    - ต้องมี credential ที่อ่าน Dev workspace ได้ (DefaultAzureCredential: env SP / az login, หรือ --interactive)
    - $items.<Type>.<name>.$id ใช้ได้เฉพาะ item ที่อยู่ใน repo (และ deploy ไป workspace เดียวกัน)
      item ที่อยู่ใน Dev แต่ไม่มี folder ใน repo จะถูกเตือนและข้ามไป
    - ชื่อ item ที่ซ้ำกันข้าม type ไม่เป็นปัญหา (key เป็น type+name) แต่ซ้ำใน type เดียวกันไม่ได้อยู่แล้วใน Fabric
    - ไม่ validate ว่า GUID "ถูกต้อง" ในเชิง semantic — แค่จับคู่กับ item จริงใน Dev ยืนยันตัวจริงหลัง deploy
      ด้วยการเช็คว่าไม่มี Dev GUID ตกค้างใน target (ดู section 14)
    - ไม่แตะ entry เดิม (merge, ไม่ overwrite) และต่อท้ายไฟล์เป็น text เหมือน generate_parameter.py

ใช้:
    python scripts/generate_parameter_all_types.py --workspace dev --dry-run
    python scripts/generate_parameter_all_types.py --workspace dev --interactive
    python scripts/generate_parameter_all_types.py --workspace <GUID>
"""

import argparse
import io
import json
import os
import re
import sys
from collections import defaultdict

import requests
import yaml

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.join(BASE_DIR, "..")
FABRIC_ITEMS_DIR = os.path.join(REPO_ROOT, "fabric_items")
PARAMETER_YML_PATH = os.path.join(FABRIC_ITEMS_DIR, "parameter.yml")
WORKSPACE_CONFIG_PATH = os.path.join(REPO_ROOT, "workspace-config.yml")

FABRIC_API = "https://api.fabric.microsoft.com/v1"
GUID_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F])")
NULL_GUID = "00000000-0000-0000-0000-000000000000"
SKIP_FILES = {".platform"}


def load_workspace_alias(name):
    if os.path.isfile(WORKSPACE_CONFIG_PATH):
        with open(WORKSPACE_CONFIG_PATH, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        if name in config:
            return config[name]
    return name


def get_token(interactive):
    if interactive:
        from azure.identity import InteractiveBrowserCredential
        credential = InteractiveBrowserCredential()
    else:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
    return credential.get_token("https://api.fabric.microsoft.com/.default").token


def fetch_workspace_items(workspace_id, token):
    """คืน {guid_lower: (type, displayName)} ของทุก item ใน workspace (รองรับ pagination)"""
    headers = {"Authorization": f"Bearer {token}"}
    items, url = {}, f"{FABRIC_API}/workspaces/{workspace_id}/items"
    while url:
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        for it in body.get("value", []):
            items[it["id"].lower()] = (it["type"], it["displayName"])
        token_next = body.get("continuationToken")
        url = f"{FABRIC_API}/workspaces/{workspace_id}/items?continuationToken={token_next}" if token_next else None
    return items


def iter_item_dirs():
    """ไล่หา item folder ผ่าน marker .platform (recursive รองรับ workspace folder) — ไม่ descend เข้า item"""
    for dirpath, dirnames, filenames in os.walk(FABRIC_ITEMS_DIR):
        if ".platform" not in filenames:
            continue
        entry = os.path.basename(dirpath)
        if "." in entry:
            name, fabric_type = entry.rsplit(".", 1)
            yield name, fabric_type, dirpath
        dirnames[:] = []


def iter_text_files(item_dir):
    for dirpath, _, filenames in os.walk(item_dir):
        for fn in filenames:
            if fn in SKIP_FILES:
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, encoding="utf-8") as f:
                    yield path, f.read()
            except (UnicodeDecodeError, OSError):
                continue  # binary file ข้ามไป


def read_logical_id(item_dir):
    try:
        with open(os.path.join(item_dir, ".platform"), encoding="utf-8") as f:
            return json.load(f)["config"]["logicalId"].lower()
    except (OSError, ValueError, KeyError):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", default="dev", help="Dev workspace GUID หรือ alias ใน workspace-config.yml")
    parser.add_argument("--interactive", action="store_true", help="login ผ่าน browser แทน DefaultAzureCredential")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dev_workspace_id = load_workspace_alias(args.workspace).lower()
    if not GUID_RE.fullmatch(dev_workspace_id):
        sys.exit(f"--workspace ต้องเป็น GUID หรือ alias ที่มีใน workspace-config.yml (ได้ '{dev_workspace_id}')")

    dev_items = fetch_workspace_items(dev_workspace_id, get_token(args.interactive))
    print(f"Dev workspace {dev_workspace_id}: พบ {len(dev_items)} items")

    repo_items = {(t, n) for n, t, _ in iter_item_dirs()}

    # logicalId ของ item ใน repo (จาก .platform) — fabric-cicd แทนเป็น id จริงของ target ให้เองตอน publish
    logical_ids = {}
    for name, fabric_type, item_dir in iter_item_dirs():
        lid = read_logical_id(item_dir)
        if lid:
            logical_ids[lid] = f"{name}.{fabric_type}"

    # lookup: id จริงของ item/workspace ใน Dev (lowercase) -> (replace_value, label)
    lookup, not_in_repo = {}, []
    lookup[dev_workspace_id] = ("$workspace.$id", "workspace")
    for guid, (itype, iname) in dev_items.items():
        if (itype, iname) not in repo_items:
            not_in_repo.append((itype, iname, guid))
            continue
        target = f"$items.{itype}.{iname}.$id"
        lookup[guid] = (target, f"{itype}.{iname}")

    # (find_value ตามที่เจอจริง, item_type ของไฟล์ที่เจอ) -> (replace_value, label, [item names ที่เจอ])
    found = {}
    unknown = defaultdict(set)  # guid -> {item ที่เจอ}
    auto_logical = defaultdict(set)  # logicalId ที่เจอ -> {item ที่เจอ}
    for name, fabric_type, item_dir in sorted(iter_item_dirs()):
        for path, text in iter_text_files(item_dir):
            for match in set(GUID_RE.findall(text)):
                key = match.lower()
                if key == NULL_GUID:
                    continue
                if key in lookup:
                    replace, label = lookup[key]
                    entry = found.setdefault((match, fabric_type), (replace, label, set()))
                    entry[2].add(f"{name}.{fabric_type}")
                elif key in logical_ids:
                    auto_logical[match].add(f"{name}.{fabric_type}")
                else:
                    unknown[match].add(f"{name}.{fabric_type}")

    existing = (yaml.safe_load(open(PARAMETER_YML_PATH, encoding="utf-8")) or {}) if os.path.isfile(PARAMETER_YML_PATH) else {}
    existing_rules = existing.get("find_replace") or []
    existing_keys = {(r.get("find_value"), r.get("item_type")) for r in existing_rules if isinstance(r, dict)}

    new_entries = []
    for (guid, item_type), (replace, label, where) in sorted(found.items(), key=lambda kv: (kv[0][1], kv[1][1], kv[0][0])):
        if (guid, item_type) in existing_keys:
            continue
        new_entries.append({"find_value": guid, "replace_value": {"_ALL_": replace}, "item_type": item_type})
        print(f"  [{item_type}] {guid} -> {replace}   (อ้างถึง {label}; เจอใน {', '.join(sorted(where))})")

    print(f"\nEntry เดิม: {len(existing_rules)} | entry ใหม่: {len(new_entries)}")

    if not_in_repo:
        print("\n⚠️  item ใน Dev ที่ไม่มี folder ใน repo (ถ้ามี item อื่นอ้างถึง จะ remap ด้วย $items ไม่ได้):")
        for itype, iname, guid in sorted(not_in_repo):
            flag = "  <-- ถูกอ้างถึงใน repo!" if guid in {k.lower() for k in unknown} else ""
            print(f"  - {itype}.{iname} ({guid}){flag}")

    if auto_logical:
        print("\nℹ️  GUID ที่เป็น logicalId ของ item ใน repo (fabric-cicd แทนให้เองตอน publish — ไม่ต้องมี rule):")
        for guid, where in sorted(auto_logical.items()):
            has_rule = any(g == guid for g, _ in existing_keys)
            print(f"  - {guid} = {logical_ids[guid.lower()]}  (เจอใน {', '.join(sorted(where))})"
                  + ("  [มี rule เดิมอยู่แล้ว — เช็คว่าจำเป็นจริงไหม]" if has_rule else ""))

    if unknown:
        print("\n⚠️  GUID ที่เจอใน repo แต่ไม่ตรงกับ item/workspace ของ Dev (external Connection, ข้าม workspace, หรืออื่นๆ — ต้องเช็ค/กรอกเอง):")
        for guid, where in sorted(unknown.items()):
            print(f"  - {guid}  (เจอใน {', '.join(sorted(where))})")

    if not new_entries:
        print("\nไม่มี entry ใหม่ — ไม่แตะไฟล์")
        return

    dumped = yaml.dump(new_entries, allow_unicode=True, sort_keys=False, default_flow_style=False)
    indented = "\n".join(f"  {l}" if l.strip() else l for l in dumped.splitlines())

    if args.dry_run:
        print("\n--dry-run: ส่วนที่จะต่อท้าย parameter.yml:\n")
        print(indented)
        return

    if not os.path.isfile(PARAMETER_YML_PATH):
        with open(PARAMETER_YML_PATH, "w", encoding="utf-8") as f:
            f.write("find_replace:\n" + indented + "\n")
    else:
        with open(PARAMETER_YML_PATH, encoding="utf-8") as f:
            text = f.read()
        # template ตั้งต้นเป็น "find_replace: []" — ต่อ list item ท้ายไฟล์ตรงๆ จะเป็น YAML ที่ผิด ต้องเปลี่ยนเป็น block ก่อน
        text = re.sub(r"^find_replace:\s*\[\]\s*$", "find_replace:", text, flags=re.MULTILINE)
        with open(PARAMETER_YML_PATH, "w", encoding="utf-8") as f:
            f.write(text.rstrip("\n") + "\n\n# --- เพิ่มโดย generate_parameter_all_types.py ---\n" + indented + "\n")
    print(f"\nเขียน {PARAMETER_YML_PATH} เรียบร้อย ({len(new_entries)} entries ใหม่)")


if __name__ == "__main__":
    sys.exit(main())
