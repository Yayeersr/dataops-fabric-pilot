# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse_name": "",
# META       "default_lakehouse_workspace_id": "",
# META       "known_lakehouses": [
# META         {
# META           "id": "350fa24a-4075-4470-a580-c5979e629bfd"
# META         }
# META       ]
# META     }
# META   }
# META }

# CELL ********************

#test 2
# from pyspark.sql.functions import when, col

# df = spark.table("sales")
# df = df.withColumn(
#     "region",
#     when(col("product_id").isin("P001"), "BKK").otherwise("CNX")
# )
# df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("sales")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# PARAMETERS CELL ********************

# Cell 1 — Parameter cell (toggle เป็น "Parameter cell" ผ่าน UI: คลิกขวา → Toggle parameter cell)
workspace_name  = "spl-cicd-dev"   # ค่า default ตอน dev — pipeline จะ inject ค่านี้ทับตอน deploy จริง
lakehouse_name  = "lh_test_cd"
table_name      = "sales"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

# Cell 2 — Imports (แยกจาก parameter cell)
from pyspark.sql import Row
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType, DateType
from pyspark.sql.functions import when, col
from datetime import date
from delta.tables import DeltaTable

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

table_path = (
    f"abfss://{workspace_name}@onelake.dfs.fabric.microsoft.com/"
    f"{lakehouse_name}.Lakehouse/Tables/dbo/{table_name}"
)

from delta.tables import DeltaTable

if not DeltaTable.isDeltaTable(spark, table_path):
    print(f"Table at '{table_path}' not found — creating with seed sample data.")
    schema = StructType([
        StructField("product_id", StringType(), False),
        StructField("quantity",   IntegerType(), True),
        StructField("amount",     DoubleType(), True),
        StructField("sales_date", DateType(), True),
    ])
    sample_data = [
        Row(product_id="P001", quantity=10, amount=1500.0, sales_date=date(2026, 9, 1)),
        Row(product_id="P002", quantity=5,  amount=750.0,  sales_date=date(2026, 9, 2)),
        Row(product_id="P003", quantity=8,  amount=1200.0, sales_date=date(2026, 9, 3)),
    ]
    df = spark.createDataFrame(sample_data, schema=schema)
else:
    df = spark.read.format("delta").load(table_path)

df = df.withColumn("region", when(col("product_id").isin("P001"), "BKK").otherwise("CNX"))

(df.write
    .format("delta")
    .mode("overwrite")
    .option("overwriteSchema", "true")
    .save(table_path))

print(f"Done. Wrote to '{table_path}'.")


# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
