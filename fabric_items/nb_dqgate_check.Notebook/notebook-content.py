# Fabric notebook source

# METADATA ********************

# META {
# META   "kernel_info": {
# META     "name": "synapse_pyspark"
# META   },
# META   "dependencies": {
# META     "lakehouse": {
# META       "default_lakehouse": "f41ea854-ad42-4c83-b646-492bfc22e7a8",
# META       "default_lakehouse_name": "lh_dqgate_test",
# META       "default_lakehouse_workspace_id": "7a829f6b-4fd1-45c7-8c8e-b7c317816e4b",
# META       "known_lakehouses": [
# META         {
# META           "id": "f41ea854-ad42-4c83-b646-492bfc22e7a8"
# META         }
# META       ]
# META     }
# META   }
# META }

# CELL ********************

%pip install "great_expectations>=1.0,<2.0"

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }

# CELL ********************

WORKSPACE_ID = "7a829f6b-4fd1-45c7-8c8e-b7c317816e4b"
LAKEHOUSE_ID = "f41ea854-ad42-4c83-b646-492bfc22e7a8"
TABLE_NAME = "dqgate_sample"

tables = [t.name for t in spark.catalog.listTables()]
if TABLE_NAME not in tables:
    seed_df = spark.createDataFrame([(1, 10), (2, 5), (3, 0)], ["id", "qty"])
    seed_df.write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable(TABLE_NAME)

import great_expectations as gx
df = spark.table(TABLE_NAME).toPandas()

_ge_context = gx.get_context(mode="ephemeral")
_ge_batch_definition = (
    _ge_context.data_sources.add_pandas("pandas")
    .add_dataframe_asset(name="dqgate")
    .add_batch_definition_whole_dataframe("batch")
)

def check_qty_not_null(pdf):
    batch = _ge_batch_definition.get_batch(batch_parameters={"dataframe": pdf})
    expectation = gx.expectations.ExpectColumnValuesToNotBeNull(column="qty")
    return batch.validate(expectation).success

result = check_qty_not_null(df)
print(f"[dqgate] qty not-null check: {'PASS' if result else 'FAIL'} ({len(df)} rows)")

if not result:
    raise AssertionError("Data quality check failed: qty มีค่า null")

# METADATA ********************

# META {
# META   "language": "python",
# META   "language_group": "synapse_pyspark"
# META }
