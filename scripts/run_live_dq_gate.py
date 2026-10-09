"""
สั่งรัน item ที่มี live DQ check อยู่ข้างใน (Data Pipeline หรือ Notebook ตรงๆ ก็ได้ — ดู
docs/check-patterns-guide.md ส่วนที่ 1) ผ่าน Fabric REST API On-Demand Job แล้ว poll job instance
จนจบ — พิสูจน์ว่าถ้า GX check ข้างในทำ raise เพราะข้อมูลเสีย จะทำให้ job instance fail จริง
และ CI เห็น/บล็อกได้ (ต่างจาก scripts/run_data_quality_checkpoint.py ที่เช็คแค่ CSV fixture
ในเครื่อง CI runner เอง ไม่ได้แตะข้อมูลจริงบน Fabric เลย)

เหตุผลที่ไม่ใช้ fabric-cicd (เหมือน deploy.py): fabric-cicd ทำแค่ publish item definition
ไม่มี API สำหรับ "รัน item แล้วรอผล" เลย — ต้องเรียก Fabric REST API ตรงๆ ด้วย credential เดียวกับ
deploy.py (ClientSecretCredential จาก FABRIC_TENANT_ID/FABRIC_CLIENT_ID/FABRIC_CLIENT_SECRET)

รองรับ 2 ชนิด item (--item-type) เพราะ endpoint ต่างกัน (ยืนยัน pattern จาก
.claude/skills/fabric-rest-api):
    pipeline:  POST /v1/workspaces/{workspaceId}/dataPipelines/{itemId}/jobs/execute/instances
    notebook:  POST /v1/workspaces/{workspaceId}/notebooks/{itemId}/jobs/execute/instances
ทั้งคู่ตอบ 202 + header Location ชี้ไปที่ job instance เดียวกันสำหรับ poll สถานะ (GET จนกว่า
status จะเป็น Succeeded/Completed/Failed/Cancelled/Deallocated) — ใช้ Notebook ตรงๆ ได้ถ้า
item ไม่จำเป็นต้องมี Pipeline ห่อ (ไม่มี activity อื่นต่อ)

รัน:
    python scripts/run_live_dq_gate.py --workspace <GUID> --item-type pipeline --item-name pl_dqgate_test
    python scripts/run_live_dq_gate.py --workspace <GUID> --item-type notebook --item-name nb_some_check
"""

import argparse
import json
import os
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from azure.identity import ClientSecretCredential

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_URL = "https://api.fabric.microsoft.com/v1"
FABRIC_SCOPE = "https://api.fabric.microsoft.com/.default"

TERMINAL_STATUSES = {"succeeded", "completed", "failed", "cancelled", "deallocated"}
SUCCESS_STATUSES = {"succeeded", "completed"}

# endpoint segment ต่อ --item-type — คนละ path กันระหว่าง Data Pipeline กับ Notebook
JOB_ENDPOINTS = {
    "pipeline": "dataPipelines",
    "notebook": "notebooks",
}


def _load_dotenv(path: str) -> None:
    # เหมือน deploy.py — โหลด .env local แบบเบาๆ ไม่มีก็ข้ามเงียบๆ ไม่ทับค่าที่มาจาก
    # GitHub Actions secrets อยู่แล้วตอนรันใน CI จริง
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _get_token() -> str:
    credential = ClientSecretCredential(
        tenant_id=os.environ["FABRIC_TENANT_ID"],
        client_id=os.environ["FABRIC_CLIENT_ID"],
        client_secret=os.environ["FABRIC_CLIENT_SECRET"],
    )
    return credential.get_token(FABRIC_SCOPE).token


def _request(method: str, path: str, token: str, body=None, params=None):
    url = BASE_URL + path
    if params:
        url += "?" + urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read()
            location = resp.headers.get("Location") or resp.headers.get("location")
            result = json.loads(raw) if raw else {}
            return resp.status, result, location
    except HTTPError as e:
        err_body = e.read().decode(errors="replace")
        sys.exit(f"::error::Fabric API {method} {path} -> HTTP {e.code}\n{err_body}")


def _list_all(path: str, token: str) -> list:
    items, continuation_token = [], None
    while True:
        params = {"continuationToken": continuation_token} if continuation_token else None
        _, result, _ = _request("GET", path, token, params=params)
        items.extend(result.get("value", []))
        continuation_token = result.get("continuationToken")
        if not continuation_token:
            break
    return items


def _find_item_id(item_type: str, workspace_id: str, item_name: str, token: str) -> str:
    segment = JOB_ENDPOINTS[item_type]
    for item in _list_all(f"/workspaces/{workspace_id}/{segment}", token):
        if item.get("displayName") == item_name:
            return item["id"]
    sys.exit(f"::error::ไม่พบ {item_type} ชื่อ '{item_name}' ใน workspace {workspace_id}")


def _poll(location: str, token: str, interval: int, timeout: int) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        req = Request(location, headers={"Authorization": f"Bearer {token}"}, method="GET")
        try:
            with urlopen(req, timeout=30) as resp:
                raw = resp.read()
                result = json.loads(raw) if raw else {}
        except HTTPError as e:
            sys.exit(f"::error::poll job instance fail -> HTTP {e.code}\n{e.read().decode(errors='replace')}")

        status = (result.get("status") or "").lower()
        if status in TERMINAL_STATUSES:
            return result
        time.sleep(interval)

    sys.exit(f"::error::job ไม่จบภายใน {timeout} วินาที (location: {location})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, help="Fabric workspace ID (GUID)")
    parser.add_argument(
        "--item-type", choices=sorted(JOB_ENDPOINTS), default="pipeline",
        help="ชนิดของ item ที่จะสั่งรัน — pipeline (ค่า default) หรือ notebook (รันตรงๆ ไม่ผ่าน pipeline)",
    )
    parser.add_argument("--item-name", default="pl_dqgate_test", help="ชื่อ Data Pipeline หรือ Notebook ที่จะสั่งรัน")
    parser.add_argument("--poll-interval", type=int, default=10, help="วินาทีระหว่างแต่ละครั้งที่ poll สถานะ")
    parser.add_argument("--timeout", type=int, default=1800, help="วินาทีสูงสุดที่รอ item จบ")
    args = parser.parse_args()

    _load_dotenv(os.path.join(BASE_DIR, "..", ".env"))
    token = _get_token()

    segment = JOB_ENDPOINTS[args.item_type]
    item_id = _find_item_id(args.item_type, args.workspace, args.item_name, token)
    print(f"พบ {args.item_type} '{args.item_name}' (id={item_id}) — เริ่มรัน...")

    _, _, location = _request(
        "POST",
        f"/workspaces/{args.workspace}/{segment}/{item_id}/jobs/execute/instances",
        token,
        body={},
    )
    if not location:
        sys.exit(f"::error::ไม่ได้รับ Location header กลับมาจาก Fabric API หลังสั่งรัน {args.item_type}")

    result = _poll(location, token, interval=args.poll_interval, timeout=args.timeout)
    final_status = (result.get("status") or "").lower()

    print(f"Job instance จบด้วยสถานะ: {result.get('status')}")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    if final_status not in SUCCESS_STATUSES:
        sys.exit(
            f"::error::live data_quality gate fail — {args.item_type} '{args.item_name}' จบด้วยสถานะ "
            f"'{result.get('status')}' (ดู detail ด้านบน หรือเปิด Fabric Monitoring Hub)"
        )

    print(f"live data_quality gate ผ่าน — {args.item_type} '{args.item_name}' {result.get('status')}")


if __name__ == "__main__":
    main()
