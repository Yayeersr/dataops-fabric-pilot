import os
import sys
import argparse
import subprocess
import yaml

# อ่าน endpoint-targets.yml แล้ววน deploy.py ให้ทุก endpoint item ที่มี target ตรงกับ
# --environment ที่รันอยู่ — เพิ่ม endpoint item ใหม่แก้แค่ endpoint-targets.yml พอ
# ไม่ต้องมาเพิ่ม job ใหม่ใน fabric-ci.yml ทุกครั้ง (ดู DataOps-CICD-Workflow.md section 14 Phase 6)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "..", "endpoint-targets.yml")
DEPLOY_SCRIPT = os.path.join(BASE_DIR, "deploy.py")

parser = argparse.ArgumentParser()
parser.add_argument("--environment", required=True)
args = parser.parse_args()

with open(CONFIG_PATH, encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}

ran_any = False
failed = []

for item_name, spec in config.items():
    workspace_id = (spec.get("targets") or {}).get(args.environment)
    if not workspace_id:
        # item นี้ไม่มี target สำหรับ environment นี้ (เช่น item ที่ authored ตรงใน endpoint
        # workspace เองไม่ต้องมี dev target แยก) — ข้ามแบบเงียบๆ ได้ ไม่ใช่ error
        continue

    ran_any = True
    repo_dir = spec.get("repo_dir", "fabric_items")
    item_path = spec["item_path"]

    cmd = [
        sys.executable, DEPLOY_SCRIPT,
        "--workspace", workspace_id,
        "--environment", args.environment,
        "--repo-dir", repo_dir,
        "--items-path", item_path,
    ]

    # flush=True เสมอ — เดิม stdout buffer แบบ block ตอนไม่ใช่ tty (เช่นใน GitHub Actions
    # runner) ทำให้ print ของ script นี้ค้างใน buffer แล้วโผล่ "หลัง" output ของ
    # subprocess (deploy.py, ซึ่งเขียนตรงเข้า fd เดิมแบบไม่ผ่าน buffer) ทำให้ log อ่านแล้ว
    # เข้าใจผิดว่า error ของ subprocess เกิด "ก่อน" ที่ script นี้จะเริ่ม deploy item นั้นซะอีก
    print(f"::group::Deploy endpoint '{item_name}' -> workspace {workspace_id} (environment={args.environment})", flush=True)
    print(" ".join(cmd), flush=True)
    result = subprocess.run(cmd)
    print("::endgroup::", flush=True)

    if result.returncode != 0:
        failed.append(item_name)

if not ran_any:
    print(f"::notice::ไม่มี endpoint item ไหนใน endpoint-targets.yml ที่มี target สำหรับ environment '{args.environment}'", flush=True)

if failed:
    print(f"::error::Endpoint deploy fail: {', '.join(failed)}", flush=True)
    sys.exit(1)
