import json


async def parse(file_bytes: bytes, filename: str):
    data = json.loads(file_bytes)
    elements = data.get("SurveyElements", [])
    questions = []
    lines = []

    for el in elements:
        if el.get("Element") != "SQ":
            continue
        payload = el.get("Payload", {})
        qid = payload.get("QuestionID", el.get("PrimaryAttribute", ""))
        qtext = payload.get("QuestionText", "")
        qtype = payload.get("QuestionType", "")
        choices = payload.get("Choices", {})
        choice_list = [v.get("Display", str(v)) if isinstance(v, dict) else str(v)
                       for v in choices.values()] if isinstance(choices, dict) else []

        questions.append({
            "question_id": qid,
            "question_text": qtext,
            "question_type": qtype,
            "choices": choice_list,
        })
        choice_str = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(choice_list))
        lines.append(f"{qid} ({qtype}): {qtext}\n{choice_str}")

    raw_text = "\n\n".join(lines) if lines else "No survey questions found."
    survey_name = data.get("SurveyEntry", {}).get("SurveyName", "")
    metadata = {"question_count": len(questions), "survey_name": survey_name}
    return raw_text, questions, metadata
