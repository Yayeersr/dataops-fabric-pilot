import os
import shutil
import tempfile
import argparse
import yaml
from fabric_cicd import FabricWorkspace, publish_all_items, unpublish_all_orphan_items
from azure.identity import ClientSecretCredential

# หา path ของ fabric_items แบบ absolute อ้างอิงจากตำแหน่งไฟล์นี้เอง (อยู่ใน scripts/ ต้องขึ้นไป 1 ชั้น)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ITEMS_DIR = os.path.join(BASE_DIR, "..", "fabric_items")

# item type ทั้งหมดที่ fabric-cicd (เวอร์ชันที่ติดตั้งจริง) รองรับ — ดึงมาจาก
# fabric_cicd.constants.ItemType เพื่อไม่ต้องมานั่งเพิ่มทีละตัวทุกครั้งที่มี item type ใหม่
# (แบบที่เจอกับ Warehouse/Dataflow มาแล้ว) — ใส่ type ที่ยังไม่มี item จริงใน repo ไว้ล่วงหน้าได้
# เพราะ fabric-cicd แค่ข้าม type ที่ไม่เจอโฟลเดอร์ folder เฉยๆ ไม่มีผลเสีย
# ถ้า fabric-cicd อัปเดตแล้วมี item type เพิ่ม ให้เช็ค ItemType enum ใน constants.py แล้ว sync list นี้อีกที
ALL_SUPPORTED_ITEM_TYPES = [
    "ApacheAirflowJob",
    "CopyJob",
    "DataAgent",
    "DataBuildToolJob",
    "DataPipeline",
    "Dataflow",
    "Environment",
    "Eventhouse",
    "Eventstream",
    "GraphQLApi",
    "KQLDashboard",
    "KQLDatabase",
    "KQLQueryset",
    "Lakehouse",
    "Map",
    "MirroredDatabase",
    "MLExperiment",
    "MountedDataFactory",
    "Notebook",
    "Ontology",
    "PaginatedReport",
    "Reflex",
    "Report",
    "SemanticModel",
    "SparkJobDefinition",
    "SQLDatabase",
    "UserDataFunction",
    "VariableLibrary",
    "Warehouse",
]


def _clean_pycache(root: str) -> None:
    # fabric-cicd ส่งทุกไฟล์ที่เจอในโฟลเดอร์ item เป็น definition part — __pycache__/*.pyc
    # ที่หลุดเข้ามา (เช่นจากรัน pytest ที่ import notebook-content.py ตรงๆ) ทำให้ publish fail
    # ด้วย error "doesn't support definition parts with empty payload"
    for dirpath, dirnames, _ in os.walk(root):
        if "__pycache__" in dirnames:
            shutil.rmtree(os.path.join(dirpath, "__pycache__"))
            dirnames.remove("__pycache__")


def _filter_parameter_file(param_path: str, item_name: str) -> None:
    # parameter.yml เดิมมี rule ของ item อื่นที่ไม่ได้อยู่ใน scoped dir นี้ด้วย (เช่น rule
    # ของ nb_endpoint_test ตอน scope แค่ lh_endpoint_test_a) — ถ้าปล่อยไว้ fabric-cicd จะ log
    # "[error] Item name '...' not found in the repository directory" ทุกครั้ง (ไม่ fail
    # จริง แค่ log น่าตกใจเปล่าๆ) กรองเหลือแค่ rule ที่ไม่ระบุ item_name (apply ทุก item)
    # หรือ item_name ตรงกับ item ที่ scope อยู่จริงเท่านั้น
    with open(param_path, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}

    for key in ("find_replace", "key_value_replace"):
        if key in config:
            config[key] = [
                rule for rule in config[key]
                if rule.get("item_name") in (None, item_name)
            ]

    with open(param_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, sort_keys=False)


def _make_scoped_items_dir(items_root: str, items_path: str) -> str:
    # จำกัด publish ให้เหลือแค่ item เดียว (ใช้ตอน pipeline/notebook กับ endpoint Lakehouse
    # ต้องไป publish เข้าคนละ workspace — ดู DataOps-CICD-Workflow.md section 14 Phase 6)
    # ทำโดยก็อป item folder ที่ต้องการ + parameter.yml เข้า temp dir แล้วชี้
    # repository_directory ไปที่ temp dir นั้นแทน items_root เดิมทั้งก้อน
    item_src = os.path.join(items_root, items_path)
    if not os.path.isdir(item_src):
        raise SystemExit(f"--items-path ไม่พบ item folder: {item_src}")

    scoped_dir = tempfile.mkdtemp(prefix="fabric_deploy_scope_")
    item_name = os.path.basename(item_src.rstrip(os.sep)).rsplit(".", 1)[0]
    shutil.copytree(item_src, os.path.join(scoped_dir, os.path.basename(item_src.rstrip(os.sep))))

    param_src = os.path.join(items_root, "parameter.yml")
    if os.path.isfile(param_src):
        param_dst = os.path.join(scoped_dir, "parameter.yml")
        shutil.copy2(param_src, param_dst)
        _filter_parameter_file(param_dst, item_name)

    return scoped_dir


def _load_dotenv(path: str) -> None:
    # โหลด .env local (สำหรับรัน deploy.py ทดสอบเองนอก CI) แบบเบาๆ ไม่เพิ่ม pip dependency
    # ใหม่ (ไม่ใช้ python-dotenv) — ไม่มีไฟล์ก็ข้ามเงียบๆ ไม่ error
    # ใช้ setdefault เสมอ ไม่ทับค่าที่ set มาจาก GitHub Actions secrets อยู่แล้วตอนรันใน CI จริง
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


parser = argparse.ArgumentParser()
parser.add_argument("--workspace", required=True, help="Fabric workspace ID (GUID)")
parser.add_argument("--environment", default="dev")
parser.add_argument(
    "--items-path",
    default=None,
    help=(
        "จำกัด publish เฉพาะ item ใต้ path นี้ (relative ต่อ fabric_items/ หรือต่อ --repo-dir "
        "ถ้าใส่ไว้ เช่น lh_endpoint_test.Lakehouse) ใช้ตอน item บางตัวต้องไป publish เข้าคนละ "
        "workspace จาก item อื่นๆ ใน repo เดียวกัน (ดู DataOps-CICD-Workflow.md section 14 Phase 6) "
        "— ถ้าใส่ flag นี้ unpublish_all_orphan_items() จะถูกข้าม เพราะ scoped dir มีแค่ "
        "item เดียว จะเข้าใจผิดว่า item อื่นในปลายทาง (ถ้ามี) เป็น orphan ทั้งหมด"
    ),
)
parser.add_argument(
    "--repo-dir",
    default=None,
    help=(
        "ใช้โฟลเดอร์อื่นแทน fabric_items/ เป็น repository_directory (relative ต่อ repo root) "
        "สำหรับกรณีมี Git Integration แยกต่างหากที่ sync item เข้าโฟลเดอร์คนละที่ (เช่น item "
        "ที่ authored จาก workspace อื่นที่ไม่ใช่ spl-cicd-dev) — ต้องมี parameter.yml ของ "
        "ตัวเองอยู่ที่ root ของโฟลเดอร์นี้ด้วยถ้าต้อง remap GUID ข้าม environment"
    ),
)
args = parser.parse_args()

_load_dotenv(os.path.join(BASE_DIR, "..", ".env"))

items_root = os.path.join(BASE_DIR, "..", args.repo_dir) if args.repo_dir else REPO_ITEMS_DIR

repo_dir = items_root
scoped_dir = None
if args.items_path:
    scoped_dir = _make_scoped_items_dir(items_root, args.items_path)
    repo_dir = scoped_dir

_clean_pycache(repo_dir)

credential = ClientSecretCredential(
    tenant_id=os.environ["FABRIC_TENANT_ID"],
    client_id=os.environ["FABRIC_CLIENT_ID"],
    client_secret=os.environ["FABRIC_CLIENT_SECRET"],
)

workspace = FabricWorkspace(
    workspace_id=args.workspace,
    environment=args.environment,
    repository_directory=repo_dir,
    item_type_in_scope=ALL_SUPPORTED_ITEM_TYPES,
    token_credential=credential,
)

try:
    publish_all_items(workspace)
except Exception as e:
    # fabric-cicd's summary exception message มีแค่ชื่อ item ที่ fail (ไม่มี error text จริง) —
    # error text จริงอยู่ใน e.additional_info (ดู fabric_cicd._common._exceptions.PublishError)
    # ใช้ getattr แทน import class ตรงๆ เพราะเป็น private module เสี่ยง break ถ้า library อัปเดต
    detail = getattr(e, "additional_info", None) or str(e)
    if "does not have access to the connection" in detail:
        print(
            "::error::Publish fail เพราะ SP ไม่มีสิทธิ์บน connection ที่ item อ้างอิง "
            "(known issue — connection ผูกกับ user ที่สร้างมันเท่านั้น ไม่ใช่ SP) "
            "ดู runbook ใน DataOps-CICD-Workflow.md section 12 "
            "('deploy-prod fail ด้วย connection-permission error → ทำยังไงต่อ') "
            "แนะนำให้คนที่มีสิทธิ์บน connection รัน scripts/deploy_local.py จากเครื่องตัวเองแทน"
        )
    raise

# ลบ item ที่ถูกลบออกจาก fabric_items/ แล้วออกจาก workspace ปลายทางด้วย (ไม่งั้นค้างอยู่ตลอด)
# Default = soft delete (เข้า recycle bin ของ workspace) ไม่ใช่ลบถาวร
# Lakehouse/Warehouse/SQL Database จะไม่ถูกลบโดย default (ต้องเปิด feature flag
# enable_lakehouse_unpublish / enable_warehouse_unpublish / enable_sqldatabase_unpublish
# เองถึงจะลบได้ — ตั้งใจไม่เปิดตรงนี้ เพราะ item พวกนี้มีข้อมูลจริงอยู่ข้างใน)
#
# ข้าม unpublish ตอน --items-path scoped ไว้ — scoped dir มีแค่ item เดียวโดยตั้งใจ
# ถ้าเรียก unpublish_all_orphan_items() ตรงนี้จะเข้าใจผิดว่า item อื่นในปลายทาง (ถ้ามี)
# เป็น orphan ทั้งหมดแล้วลบทิ้ง ทั้งที่จริงแค่ไม่ได้อยู่ใน scope ของ deploy ครั้งนี้
if args.items_path:
    print(
        "::warning::ข้าม unpublish_all_orphan_items() เพราะรันแบบ --items-path scoped "
        f"({args.items_path}) — ดู DataOps-CICD-Workflow.md section 14 Phase 6"
    )
else:
    unpublish_all_orphan_items(workspace)

if scoped_dir:
    shutil.rmtree(scoped_dir, ignore_errors=True)
