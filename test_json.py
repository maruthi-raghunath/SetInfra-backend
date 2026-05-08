import json
from pydantic import BaseModel, Field

class QueryPlan(BaseModel):
    target_tables: list[str] = Field(default_factory=list)
    sql: str
    chart_type: str

def _parse_query_plan(raw_text: str) -> dict:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    parsed = json.loads(cleaned)
    validated = QueryPlan.model_validate(parsed)
    return validated.model_dump()

raw = """{
  "target_tables": ["sdtm_cm", "sdtm_ae"],
  "sql": "SELECT 'Medication' AS type, CMTRT AS event_name, CMSTDY AS study_day FROM sdtm_cm WHERE SUBJ = '435' AND CMSTDY IS NOT NULL UNION ALL SELECT 'Adverse Event' AS type, AETERM AS event_name, AESTDY AS study_day FROM sdtm_ae WHERE SUBJ = '435' AND AESTDY IS NOT NULL ORDER BY study_day ASC",
  "chart_type": "timeline"
}"""

print(_parse_query_plan(raw))
