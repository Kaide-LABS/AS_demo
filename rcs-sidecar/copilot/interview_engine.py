import os
import json
import uuid
import redis.asyncio as redis
from fastapi import UploadFile
from schemas import InterviewResponse, FieldState
from field_state import FieldStateEngine
from copilot.question_generator import generate_next_question
from copilot.answer_normalizer import normalize_answer
from theater import TheaterBroadcaster

REDIS_URL = os.getenv("REDIS_URL")

class InterviewEngine:
    def __init__(self):
        self._redis = redis.from_url(REDIS_URL) if REDIS_URL else None

    async def _save_state(self, job_id: str, state: dict):
        if self._redis:
            await self._redis.set(f"interview:{job_id}", json.dumps(state))

    async def _load_state(self, job_id: str) -> dict:
        if self._redis:
            data = await self._redis.get(f"interview:{job_id}")
            if data:
                return json.loads(data)
        return {}

    async def start(self, project_id: str, brief: str, job_id: str = None) -> InterviewResponse:
        job_id = job_id or str(uuid.uuid4())
        broadcaster = TheaterBroadcaster(job_id)
        
        fs_engine = FieldStateEngine()
        field_states = fs_engine.export()
        
        conversation = [{"role": "system", "content": f"Brief: {brief}"}]
        
        question = await generate_next_question(field_states, conversation, broadcaster)
        conversation.append({"role": "assistant", "content": question})
        
        state = {
            "project_id": project_id,
            "brief": brief,
            "field_states": {k: v.value for k, v in field_states.items()},
            "conversation": conversation,
            "uploaded_artifact_ids": [],
            "turn_count": 1,
        }
        await self._save_state(job_id, state)
        
        return InterviewResponse(
            job_id=job_id,
            question=question,
            field_state_summary=field_states,
            fields_remaining=fs_engine.count_unknown(),
            fields_total=len(field_states)
        )

    async def respond(self, job_id: str, user_answer: str, uploaded_files: list[UploadFile] = None) -> InterviewResponse:
        broadcaster = TheaterBroadcaster(job_id)
        state = await self._load_state(job_id)
        if not state:
            raise Exception("Interview session not found")
            
        state["conversation"].append({"role": "user", "content": user_answer})
        
        target_fields = [k for k, v in state["field_states"].items() if v != FieldState.VALIDATED.value]
        normalized = await normalize_answer(user_answer, target_fields, broadcaster)
        
        for ans in normalized.normalized:
            if ans.field_path in state["field_states"]:
                state["field_states"][ans.field_path] = FieldState.CANDIDATE.value if ans.needs_file_evidence else FieldState.VALIDATED.value
                
        # Mocking synthesis condition for simplicity
        missing_count = sum(1 for v in state["field_states"].values() if v == FieldState.UNKNOWN.value)
        
        if missing_count == 0:
            question = None
            calibration = None # In reality call synthesis_agent
        else:
            question = await generate_next_question(
                {k: FieldState(v) for k, v in state["field_states"].items()}, 
                state["conversation"], 
                broadcaster
            )
            state["conversation"].append({"role": "assistant", "content": question})
            calibration = None
            
        state["turn_count"] += 1
        await self._save_state(job_id, state)
        
        return InterviewResponse(
            job_id=job_id,
            question=question,
            field_state_summary={k: FieldState(v) for k, v in state["field_states"].items()},
            fields_remaining=missing_count,
            fields_total=len(state["field_states"]),
            calibration=calibration,
            suggested_upload="Upload a brand guidelines PDF" if any(a.needs_file_evidence for a in normalized.normalized) else None
        )

    async def get_state(self, job_id: str) -> dict:
        return await self._load_state(job_id)
