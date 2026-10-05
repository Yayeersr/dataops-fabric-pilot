"""
ตรวจหลัง deploy ว่าไม่มี GUID ของ Dev ตกค้างอยู่ใน item ของ target environment (อ่านอย่างเดียว ไม่แก้อะไรใน Fabric)

ทำไมต้องมี:
    parameter.yml / fabric-cicd remap GUID ตอน deploy แต่ถ้า rule ขาดหรือ find_value ผิดตัว มันไม่ error —
    item ใน prod จะชี้กลับ Dev เงียบๆ (รันผ่านแต่ข้อมูลไปผิดที่) สคริปต์ offline (debug_parameterization.py) ตรวจ
    ได้แค่โครงสร้างไฟล์ ตัวนี้ตรวจ "ของจริงที่อยู่ใน target workspace หลัง deploy"

วิธีตรวจ:
    1. ดึงรายการ item ของ source (Dev) และ target (เช่น prod) จาก Fabric REST API
    2. ดึง definition ของทุก item ใน target (getDefinition) แล้วสแกนทุกไฟล์หา GUID
    3. ห้ามเจอ GUID ต่อไปนี้ใน target:
         - id ของ workspace Dev
         - id ของ item ใดๆ ใน Dev
         - find_value ทุกตัวใน parameter.yml (= GUID ของ Dev ที่ rule ควรเปลี่ยนให้หมด รวมถึง id เก่าที่ item
           ถูกสร้างใหม่ไปแล้วและไม่อยู่ใน Dev อีก)
         - GUID เพิ่มเติมที่ระบุผ่าน --forbid
       เจอ = FAIL (exit code 1 ใช้ใน CI ได้)
    4. GUID ที่เป็น id ของ target workspace/item หรือ logicalId ของ item ใน target = OK
    5. GUID อื่นๆ (external Connection ID, item ข้าม workspace ฯลฯ) = INFO แสดงให้คนดู ไม่ถือว่า fail
       ใช้ --allow เพื่อซ่อนตัวที่รู้แล้วว่าตั้งใจ (เช่น endpoint workspace ที่ hardcode)

ข้อจำกัด:
    - ตรวจได้เฉพาะ item type ที่ API getDefinition รองรับ type ที่ดึงไม่ได้จะแสดงเป็น SKIPPED ไม่ใช่ผ่าน
    - "ไม่เจอ GUID ของ Dev" ไม่ได้พิสูจน์ว่าชี้ถูกที่ — แค่ยืนยันว่าไม่ได้ชี้กลับ Dev ถ้า rule แทนเป็น GUID ผิดตัวอื่น
      จะไปอยู่ใน INFO ให้ตรวจเอง
    - GUID ที่ Fabric ฝังในรูปแบบอื่น (เช่นห่อใน JSON string ที่ escape) จับได้เฉพาะที่เป็นข้อความ GUID ตรงๆ
    - ต้องมี credential ที่อ่านทั้ง 2 workspace ได้ (DefaultAzureCredential หรือ --interactive)

ใช้:
    python scripts/verify_deployed_guids.py --source <DEV_WS_GUID> --target <PROD_WS_GUID> --interactive
    python scripts/verify_deployed_guids.py --source <DEV> --target <PROD> --allow <GUID> --allow <GUID>
"""

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from collections import defaultdict

import requests
import yaml

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PARAMETER_YML = os.path.join(BASE_DIR, "..", "fabric_items", "parameter.yml")
API = "https://api.fabric.microsoft.com/v1"
GUID_RE = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F])")
NULL_GUID = "00000000-0000-0000-0000-000000000000"


def get_token(interactive):
    if interactive:
        from azure.identity import InteractiveBrowserCredential
        credential = InteractiveBrowserCredential()
    else:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
    return credential.get_token("https://api.fabric.microsoft.com/.default").token


def request(method, url, headers, **kwargs):
    """เรียก API พร้อม retry เมื่อโดน rate limit (429)"""
    for _ in range(6):
        resp = requests.request(method, url, headers=headers, timeout=60, **kwargs)
        if resp.status_code != 429:
            return resp
        time.sleep(int(resp.headers.get("Retry-After", 5)))
    return resp


def fetch_items(workspace_id, headers):
    items, url = [], f"{API}/workspaces/{workspace_id}/items"
    while url:
        resp = request("GET", url, headers)
        resp.raise_for_status()
        body = resp.json()
        items += body.get("value", [])
        nxt = body.get("continuationToken")
        url = f"{API}/workspaces/{workspace_id}/items?continuationToken={nxt}" if nxt else None
    return items


def get_definition_parts(workspace_id, item_id, headers):
    """คืน list ของ {path, payload(base64)} หรือ None ถ้า item type นี้ดึง definition ไม่ได้"""
    resp = request("POST", f"{API}/workspaces/{workspace_id}/items/{item_id}/getDefinition", headers)
    if resp.status_code == 202:  # long-running operation: poll จน Succeeded แล้วอ่าน /result
        op_url = resp.headers["Location"]
        for _ in range(60):
            time.sleep(int(resp.headers.get("Retry-After", 2)))
            state = request("GET", op_url, headers)
            if state.status_code == 200 and state.json().get("status") == "Succeeded":
                resp = request("GET", op_url.rstrip("/") + "/result", headers)
                break
            if state.status_code == 200 and state.json().get("status") in ("Failed", "Cancelled"):
                return None
        else:
            return None
    if resp.status_code != 200:
        return None
    return resp.json().get("definition", {}).get("parts", [])


def load_parameter_find_values(path):
    if not path or not os.path.isfile(path):
        return set()
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    values = set()
    for rule in config.get("find_replace") or []:
        if isinstance(rule, dict):
            for g in GUID_RE.findall(str(rule.get("find_value", ""))):
                values.add(g.lower())
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="workspace GUID ของ Dev (ต้นทาง)")
    parser.add_argument("--target", required=True, help="workspace GUID ของ environment ที่เพิ่ง deploy (เช่น prod)")
    parser.add_argument("--parameter-file", default=DEFAULT_PARAMETER_YML, help="parameter.yml ที่ใช้ดึง find_value เป็น GUID ต้องห้าม")
    parser.add_argument("--forbid", action="append", default=[], help="GUID เพิ่มเติมที่ห้ามเจอใน target (ใส่ซ้ำได้)")
    parser.add_argument("--allow", action="append", default=[], help="GUID ที่รู้แล้วว่าตั้งใจให้อยู่ (ซ่อนจาก INFO)")
    parser.add_argument("--interactive", action="store_true")
    args = parser.parse_args()

    source, target = args.source.lower(), args.target.lower()
    if source == target:
        sys.exit("--source และ --target ต้องเป็นคนละ workspace")

    print("1/3 login... (ถ้าใช้ --interactive ให้ดูหน้าเบราว์เซอร์ที่เด้งขึ้นมา — มักซ่อนอยู่หลังหน้าต่างอื่น)", flush=True)
    headers = {"Authorization": f"Bearer {get_token(args.interactive)}"}
    print("2/3 ดึงรายการ item ของ source และ target...", flush=True)
    source_items = fetch_items(source, headers)
    target_items = fetch_items(target, headers)

    # GUID ที่ "ห้าม" เจอใน target ->  คำอธิบายว่าคืออะไร
    forbidden = {source: "Dev workspace"}
    for it in source_items:
        forbidden[it["id"].lower()] = f"Dev item {it['type']}.{it['displayName']}"
    for g in load_parameter_find_values(args.parameter_file):
        forbidden.setdefault(g, "find_value ใน parameter.yml (GUID ของ Dev ที่ควรถูก remap)")
    for g in args.forbid:
        forbidden.setdefault(g.lower(), "ระบุผ่าน --forbid")

    target_ids = {target: "target workspace"}
    for it in target_items:
        target_ids[it["id"].lower()] = f"target item {it['type']}.{it['displayName']}"
    # id ที่อยู่ทั้งใน Dev และ target (ไม่ควรเกิด แต่กัน false positive ถ้า source/target ปนกัน)
    for g in list(forbidden):
        if g in target_ids:
            del forbidden[g]

    allow = {g.lower() for g in args.allow}
    print(f"source (Dev): {len(source_items)} items | target: {len(target_items)} items | GUID ต้องห้าม: {len(forbidden)}")

    fails, infos, skipped, checked = [], defaultdict(set), [], 0
    ordered = sorted(target_items, key=lambda i: (i["type"], i["displayName"]))
    for n, it in enumerate(ordered, 1):
        label = f"{it['type']}.{it['displayName']}"
        started = time.time()
        print(f"3/3 [{n}/{len(ordered)}] {label} ...", end=" ", flush=True)
        parts = get_definition_parts(target, it["id"], headers)
        if parts is None:
            print(f"ข้าม ({time.time() - started:.0f}s)", flush=True)
            skipped.append(label)
            continue
        print(f"ok ({time.time() - started:.0f}s)", flush=True)
        checked += 1

        texts, own_logical = [], None
        for part in parts:
            try:
                text = base64.b64decode(part["payload"]).decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                continue
            if part["path"] == ".platform":
                try:
                    own_logical = json.loads(text)["config"]["logicalId"].lower()
                except (ValueError, KeyError):
                    pass
                continue  # .platform ไม่ต้อง remap
            texts.append((part["path"], text))

        for path, text in texts:
            for g in set(GUID_RE.findall(text)):
                k = g.lower()
                if k == NULL_GUID or k in allow or k in target_ids or k == own_logical:
                    continue
                if k in forbidden:
                    fails.append((label, path, g, forbidden[k]))
                else:
                    infos[g].add(label)

    print(f"ตรวจแล้ว {checked} items | ข้าม (ดึง definition ไม่ได้) {len(skipped)} items")
    if skipped:
        print("  SKIPPED:", ", ".join(skipped))

    if infos:
        print("\nINFO: GUID ที่ไม่ใช่ id ของ Dev และไม่ใช่ id ของ target (อาจเป็น logicalId, connection, item ข้าม workspace — ตรวจเอง):")
        for g, where in sorted(infos.items()):
            print(f"  - {g}  ({', '.join(sorted(where))})")

    if fails:
        print(f"\nFAIL: เจอ GUID ของ Dev ตกค้างใน target {len(fails)} จุด:")
        for label, path, g, why in fails:
            print(f"  - {label} / {path}: {g}  = {why}")
        return 1

    print("\nPASS: ไม่พบ GUID ของ Dev ตกค้างใน item ที่ตรวจ" + (" (แต่มี item ที่ข้าม — ดู SKIPPED)" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
