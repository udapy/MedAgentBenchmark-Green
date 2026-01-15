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

        # 2. Pick tasks
        tasks_to_run = []
        
        # Check for list of task_ids
        requested_ids = request.config.get("task_ids")
        if requested_ids and isinstance(requested_ids, list):
            for tid in requested_ids:
                task = self.agent.select_task(task_id=tid)
                if task:
                    tasks_to_run.append(task)
                else:
                    logger.warning(f"Task ID {tid} not found, skipping.")
            
            if not tasks_to_run:
                await updater.reject(new_agent_text_message(f"No valid tasks found from provided list: {requested_ids}"))
                return
        
        # Fallback to single forced task or random
        if not tasks_to_run:
            forced_task_id = request.config.get("force_task_id")
            task = self.agent.select_task(task_id=forced_task_id)
            if not task:
                await updater.reject(new_agent_text_message("Failed to select a valid task."))
                return
            tasks_to_run.append(task)

        # Config extraction
        interaction_limit = request.config.get("max_iterations", 8)
        
        total_tasks = len(tasks_to_run)
        logger.info(f"Starting execution of {total_tasks} tasks.")

        # 3. External Orchestration (Loop)
        for i, task in enumerate(tasks_to_run):
            task_id = task.get("id", "unknown")
            await updater.update_status(TaskState.working, new_agent_text_message(f"[{i+1}/{total_tasks}] Selected Task: {task_id}"))

            try:
                 result = await self.agent.run_assessment(task, participants, updater, interaction_limit=interaction_limit)
            except Exception as e:
                 logger.exception(f"Assessment execution failed for task {task_id}")
                 await updater.update_status(TaskState.failed, new_agent_text_message(f"Execution error for {task_id}: {e}"))
                 # Verify strategy: continue to next task or abort? 
                 # Usually continue is better for batch benchmarks.
                 continue

            # 4. Final Artifact per task
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
    
            logger.info(f"Assessment complete for {task_id}. Score: {result.score}")
            
            await updater.add_artifact(
                parts=[
                    Part(root=TextPart(text=f"Task: {task['instruction']}\nGrade: {result.feedback}\nScore: {result.score}")),
                    Part(root=DataPart(data=artifact_content))
                ],
                name=f"evaluation_result_{task_id}", # Unique name per task
            )

