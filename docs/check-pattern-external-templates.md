# Check Pattern External Templates — Research Notes

สรุปว่าแต่ละ check pattern (`unit_test` / `data_quality` / `structure` / `schema` / `none`) ใน `ci-config.yml` มี template/framework จากภายนอกรองรับอยู่แล้วไหม เทียบกับ script ที่ repo นี้เขียนเอง

## สถานะปัจจุบันของแต่ละ pattern ใน repo นี้

| Pattern | Script/config ที่ใช้อยู่ | มี external framework รองรับไหม |
|---|---|---|
| `unit_test` | `tests/unit/test_<name>.py` — ใช้ pytest | pytest เป็น framework มาตรฐาน |
| `data_quality` | `scripts/run_data_quality_checkpoint.py` + `great_expectations/checkpoints/dq_*.yml` | มี — ใช้ Great Expectations (GX) 1.x Python API ตรงๆ |
| `structure` | `scripts/validate_pipeline_structure.py` | ไม่มี — เขียนเอง 100% |
| `schema` | `scripts/validate_schema_contract.py` | ไม่มี — ยังเป็น placeholder ใน pilot repo นี้ |
| `none` | ไม่มี check | ไม่เกี่ยวข้อง |

## รายละเอียดต่อ pattern

### `unit_test`

**แนวทางที่ 1 — pytest ตรงกับ pandas/Spark dataframe** ([Kevin Chant](https://www.kevinrchant.com/2024/08/30/unit-tests-on-microsoft-fabric-items/)):

```python
geographydf = spark.sql("SELECT * FROM AzDoUnitTestingLH.Geography")
pd_geographydf = geographydf.toPandas()

def test_no_missing_values(test_dataframe):
    missing = test_dataframe.isnull().sum().sum()
    assert missing == 0, f"Found {missing} missing values"
```

แนวนี้ทดสอบ "ผลลัพธ์ข้อมูล" ตรงๆ — จริงๆ ใกล้กับ pattern `data_quality` ของเรามากกว่า `unit_test`

**แนวทางที่ 2 — Microsoft's official `data-factory-testing-framework`** รองรับ Fabric Data Pipeline ด้วย (`TestFrameworkType.Fabric`):

```python
from data_factory_testing_framework import TestFramework, TestFrameworkType
from data_factory_testing_framework.state import PipelineRunState, RunParameter

def test_directory_parameter(pipeline: Pipeline):
    activity = pipeline.get_activity_by_name("Copy sample data")
    state = PipelineRunState(parameters=[
        RunParameter(RunParameterType.Pipeline, name="DirectoryName", value="SampleData")
    ])
    activity.evaluate(state)
    assert activity.type_properties["sink"]["datasetSettings"]["typeProperties"]["location"]["folderPath"].result == "SampleData"
```

นี่คือ external template ที่ pip install ได้จริง ใช้ evaluate expression/parameter ในตัว pipeline activity โดยไม่ต้องรันจริงบน Fabric runtime — ตรงกับงานที่ `unit_test` ควรทำ ยังมี [`pytestmsfabric`](https://pypi.org/project/pytestmsfabric/) (PyPI) เป็น pytest plugin เฉพาะสำหรับ Fabric notebook/data quality อีกตัวที่น่าดู

### `data_quality`

Great Expectations 1.x ("GX Core") — **ตรงกับที่ `run_data_quality_checkpoint.py` ทำอยู่แบบเป๊ะๆ**:

```
gx.get_context() → add_pandas source → add_dataframe_asset → ExpectationSuite → Checkpoint.run()
```

นี่คือ pattern ทางการของ GX เอง ไม่ใช่ของเราคิดเอง (GX 1.x ตัด CLI/YAML checkpoint แบบเก่าออกแล้วจริง ต้องเรียกผ่าน Python API แบบนี้เท่านั้น) — สรุปคือ pattern นี้ตรงกับ external template อยู่แล้ว ไม่ต้องแก้อะไร

อ้างอิง: [GX Core overview](https://docs.greatexpectations.io/docs/core/introduction/gx_overview/), [Python-first API in 1.x](https://theneuralbase.com/great-expectations/learn/beginner/python-first-api-in-1-x/)

### `structure`

**`Azure/data-factory-validate-action`** — GitHub Action สำเร็จรูปที่ validate ADF/pipeline resource ทั้งหมดใน repo ก่อน deploy:

```yaml
steps:
  - uses: Azure/data-factory-validate-action@v1.1.6
    with:
      path: ./adf
```

ใช้ `@microsoft/azure-data-factory-utilities` npm package ข้างใน — **แต่ archived ตั้งแต่ มิ.ย. 2024** ไม่ maintain แล้ว และเป็น ADF ไม่ใช่ Fabric โดยตรง (format ต่างกันบ้าง) ดังนั้น `validate_pipeline_structure.py` แบบเขียนเองยังสมเหตุสมผลอยู่ — แต่ `data-factory-testing-framework` (ตัวเดียวกับ `unit_test` ด้านบน) ก็ตรวจ reference/evaluate activity ได้เหมือนกัน อาจเอามาทดแทนของ custom ได้ถ้าอยากใช้ library ที่ยัง maintain อยู่

อ้างอิง: [Azure/data-factory-validate-action (archived)](https://github.com/Azure/data-factory-validate-action)

### `schema`

**Data Contract CLI / ODCS (Open Data Contract Standard)** — ตรงกับ use case ของ `schema` pattern มากที่สุด: เขียน schema contract เป็น YAML แล้วรัน `datacontract test` เทียบกับ data source จริง:

```
datacontract import snowflake --source <account> --database ORDER_DB --schema PUBLIC --output datacontract.yaml
datacontract test datacontract.yaml
```

รองรับ CI/CD (review ผ่าน PR, lint/test อัตโนมัติ), มี connector หลายตัว (ไม่มี Fabric ตรงๆ แต่รองรับผ่าน generic SQL/warehouse connector ได้) — เอามาแทนที่ placeholder ของ `validate_schema_contract.py` ได้จริงถ้าต้องการทำ pattern นี้ให้ใช้งานได้จริงเป็นครั้งแรก ทางเลือกใกล้เคียงอีกทางคือ dbt's [model contracts](https://docs.getdbt.com/docs/mesh/govern/model-contracts) ถ้าทีมมี dbt อยู่แล้ว

อ้างอิง: [What is Data Contract CLI?](https://docs.datacontract.com/)

## สรุปเชิง action

- `data_quality` ตรง external template อยู่แล้ว ไม่ต้องแก้
- `unit_test` / `structure` มี library ทางการ (`data-factory-testing-framework`) ที่น่าลองแทน custom `importlib`/validator ปัจจุบัน
- `schema` มี Data Contract CLI เป็นตัวเลือกที่ตรงโจทย์ที่สุดถ้าจะทำให้ pattern นี้ใช้งานได้จริงเป็นครั้งแรก

## Sources

- [Unit tests on Microsoft Fabric items — K Chant](https://www.kevinrchant.com/2024/08/30/unit-tests-on-microsoft-fabric-items/)
- [Automate testing Microsoft Fabric Data Pipelines with Azure DevOps — K Chant](https://www.kevinrchant.com/2025/04/22/automate-testing-microsoft-fabric-data-pipelines-with-azure-devops/)
- [pytestmsfabric — PyPI](https://pypi.org/project/pytestmsfabric/)
- [GX Core overview — Great Expectations](https://docs.greatexpectations.io/docs/core/introduction/gx_overview/)
- [Python-first API in 1.x — The Neural Base](https://theneuralbase.com/great-expectations/learn/beginner/python-first-api-in-1-x/)
- [Azure/data-factory-validate-action — GitHub (archived)](https://github.com/Azure/data-factory-validate-action)
- [What is Data Contract CLI?](https://docs.datacontract.com/)
- [Model contracts — dbt Developer Hub](https://docs.getdbt.com/docs/mesh/govern/model-contracts)
- [Auto-profiling with Data Assistants — The Neural Base](https://theneuralbase.com/great-expectations/learn/intermediate/auto-profiling-with-data-assistants/)
- [expect_column_pair_values_a_to_be_greater_than_b — GX docs](https://greatexpectations.io/legacy/v1/expectations/expect_column_pair_values_a_to_be_greater_than_b/) — confirms lowercase-only naming (case-sensitive in v3+)
- [GX expectation name case-sensitivity issue #3506](https://github.com/great-expectations/great_expectations/issues/3506)
