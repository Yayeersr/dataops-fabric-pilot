# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "5212c2cd-e35b-40f7-ba1f-110fc2c5a899",
# META       "default_lakehouse_name": "lh_endpoint_lab",
# META       "default_lakehouse_workspace_id": "30e32f68-1cee-419b-be00-c0671b00f7af",
# META       "known_lakehouses": [
# META         {
# META           "id": "5212c2cd-e35b-40f7-ba1f-110fc2c5a899"
# META         }
# META       ]
# META     }
# META   }
# META }

# CELL ********************

# ====== แก้บรรทัดนี้บรรทัดเดียว — ใส่ชื่อย่อของตัวเอง (a-z ตัวเล็ก/ตัวเลข) ======
name = "zz1"


def build_table_name(learner_name):
    """ตั้งชื่อ table ปลายทางเป็น ci_endpoint_test_lab_<ชื่อ> เสมอ กันชื่อชนกับเพื่อนคนอื่น"""
    return f"ci_endpoint_test_lab_{learner_name}"


table_name = build_table_name(name)

# GUID ของ workspace/lakehouse "dev" ที่ facilitator เตรียมไว้ให้แล้ว — ไม่ต้องแก้ 2 บรรทัดนี้
ENDPOINT_WORKSPACE_ID = "30e32f68-1cee-419b-be00-c0671b00f7af"   # spl-cicd-endpoint-dev
ENDPOINT_LAKEHOUSE_ID = "5212c2cd-e35b-40f7-ba1f-110fc2c5a899"   # lh_endpoint_lab (dev)

endpoint_path = (
    f"abfss://{ENDPOINT_WORKSPACE_ID}@onelake.dfs.fabric.microsoft.com"
    f"/{ENDPOINT_LAKEHOUSE_ID}/Tables/{table_name}"
)

# เขียนจริงเข้า Lakehouse เฉพาะตอนรันในเครื่องมือ Fabric (มี spark session ให้ใช้) —
# ถ้าไฟล์นี้ถูก import ไปเทสด้วย pytest (ไม่มี spark) จะข้ามส่วนนี้ไปเฉยๆ ไม่ error
if "spark" in dir():
    df = spark.createDataFrame([(1, f"hello from {name}")], ["id", "message"])
    df.write.format("delta").mode("overwrite").save(endpoint_path)
    print(f"เขียนเข้า table: {table_name}")
else:
    print(f"[dry-run นอก Fabric] จะเขียนเข้า table: {table_name} ที่ {endpoint_path}")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
