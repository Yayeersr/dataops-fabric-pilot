"""
รัน Data Pipeline ที่มี live DQ check อยู่ข้างใน (เช่น pl_dqgate_test -> nb_dqgate_check) ผ่าน
Fabric REST API On-Demand Job แล้ว poll job instance จนจบ — พิสูจน์ว่าถ้า Notebook Activity
ข้างในทำ GX check แล้ว raise เพราะข้อมูลเสีย จะทำให้ pipeline job instance fail จริง และ CI
เห็น/บล็อกได้ (ต่างจาก scripts/run_data_quality_checkpoint.py ที่เช็คแค่ CSV fixture ในเครื่อง
CI runner เอง ไม่ได้แตะข้อมูลจริงบน Fabric เลย)

เหตุผลที่ไม่ใช้ fabric-cicd (เหมือน deploy.py): fabric-cicd ทำแค่ publish item definition
ไม่มี API สำหรับ "รัน item แล้วรอผล" เลย — ต้องเรียก Fabric REST API ตรงๆ ด้วย credential เดียวกับ
deploy.py (ClientSecretCredential จาก FABRIC_TENANT_ID/FABRIC_CLIENT_ID/FABRIC_CLIENT_SECRET)

Endpoint ที่ใช้ (ยืนยัน pattern จาก .claude/skills/fabric-rest-api):
    POST /v1/workspaces/{workspaceId}/dataPipelines/{pipelineId}/jobs/execute/instances
    -> 202 + header Location ชี้ไปที่ job instance เดียวกันสำหรับ poll สถานะ (GET จนกว่า
       status จะเป็น Succeeded/Completed/Failed/Cancelled/Deallocated)

รัน:
    python scripts/run_live_dq_gate.py --workspace <GUID> --pipeline-name pl_dqgate_test
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


def _find_pipeline_id(workspace_id: str, pipeline_name: str, token: str) -> str:
    for item in _list_all(f"/workspaces/{workspace_id}/dataPipelines", token):
        if item.get("displayName") == pipeline_name:
            return item["id"]
    sys.exit(f"::error::ไม่พบ Data Pipeline ชื่อ '{pipeline_name}' ใน workspace {workspace_id}")


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

    sys.exit(f"::error::pipeline job ไม่จบภายใน {timeout} วินาที (location: {location})")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, help="Fabric workspace ID (GUID)")
    parser.add_argument("--pipeline-name", default="pl_dqgate_test")
    parser.add_argument("--poll-interval", type=int, default=10, help="วินาทีระหว่างแต่ละครั้งที่ poll สถานะ")
    parser.add_argument("--timeout", type=int, default=1800, help="วินาทีสูงสุดที่รอ pipeline จบ")
    args = parser.parse_args()

    _load_dotenv(os.path.join(BASE_DIR, "..", ".env"))
    token = _get_token()

    pipeline_id = _find_pipeline_id(args.workspace, args.pipeline_name, token)
    print(f"พบ pipeline '{args.pipeline_name}' (id={pipeline_id}) — เริ่มรัน...")

    _, _, location = _request(
        "POST",
        f"/workspaces/{args.workspace}/dataPipelines/{pipeline_id}/jobs/execute/instances",
        token,
        body={},
    )
    if not location:
        sys.exit("::error::ไม่ได้รับ Location header กลับมาจาก Fabric API หลังสั่งรัน pipeline")

    result = _poll(location, token, interval=args.poll_interval, timeout=args.timeout)
    final_status = (result.get("status") or "").lower()

    print(f"Pipeline job instance จบด้วยสถานะ: {result.get('status')}")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))

    if final_status not in SUCCESS_STATUSES:
        sys.exit(
            f"::error::live data_quality gate fail — pipeline '{args.pipeline_name}' จบด้วยสถานะ "
            f"'{result.get('status')}' (ดู detail ด้านบน หรือเปิด Fabric Monitoring Hub)"
        )

    print(f"live data_quality gate ผ่าน — pipeline '{args.pipeline_name}' {result.get('status')}")


if __name__ == "__main__":
    main()
