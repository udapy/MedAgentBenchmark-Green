import logging
import json
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart, DataPart
from a2a.utils import get_message_text, new_agent_text_message
from pydantic import ValidationError

from src.a2a_adapter.models import EvalRequest, EvalResult
from src.green_agent.core import GreenHealthcareAgent

logger = logging.getLogger(__name__)

class GreenExecutor:
    def __init__(self):
        self.agent = GreenHealthcareAgent()

    async def execute(self, message: Message, updater: TaskUpdater) -> None:
        """
        Main execution loop:
        1. Validate request
        2. Initialize agent/tasks
        3. Orchestrate
        4. Grade & Produce Artifact
        """
        input_text = get_message_text(message)
        logger.info(f"Received assessment request: {input_text}")

        # 1. Validate
        try:
            request: EvalRequest = EvalRequest.model_validate_json(input_text)
        except ValidationError as e:
            await updater.reject(new_agent_text_message(f"Invalid request format: {e}"))
            return

        participants = request.participants
        if not participants:
            await updater.reject(new_agent_text_message("No participants provided."))
            return

        # Initialize domain agent
        await self.agent.initialize() # Ensure FHIR/Data ready

        # 2. Pick a task
        # Allow config override for deterministic testing
        forced_task_id = request.config.get("force_task_id")
        task = self.agent.select_task(task_id=forced_task_id)
        
        if not task:
            await updater.reject(new_agent_text_message("Failed to select a valid task."))
            return

        task_id = task.get("id", "unknown")
        await updater.update_status(TaskState.working, new_agent_text_message(f"Selected Task: {task_id}"))

        # 3. External Orchestration (Loop)
        # For this specific benchmark, it's a simple 1-turn or multi-turn exchange managed by the agent core logic
        # We delegate the actual interaction to the agent's logic to keep this adapter clean
        
        # Assumption: The agent logic handles the communication loop and returns a result
        # We pass the updater so it can stream progress
        try:
             result = await self.agent.run_assessment(task, participants, updater)
        except Exception as e:
             logger.exception("Assessment execution failed")
             await updater.update_status(TaskState.failed, new_agent_text_message(f"Execution error: {e}"))
             return

        # 4. Final Artifact
        # Ensure strict adherence to agentbeats-tutorial artifact schema
        artifact_content = {
            "score": result.score,
            "feedback": result.feedback,
            "task_id": result.task_id,
            "metadata": result.metadata,
            "artifact_type": "evaluation_result" 
        }
        
        # Add timestamp if not present
        if "timestamp" not in artifact_content:
            artifact_content["timestamp"] = datetime.now(timezone.utc).isoformat()

        logger.info(f"Assessment complete. Score: {result.score}")
        
        await updater.add_artifact(
            parts=[
                Part(root=TextPart(text=f"Task: {task['instruction']}\nGrade: {result.feedback}\nScore: {result.score}")),
                Part(root=DataPart(data=artifact_content))
            ],
            name="evaluation_result", # Standard name
        )
