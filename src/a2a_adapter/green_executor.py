
import logging
import json
import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, Any

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart, DataPart
from a2a.utils import get_message_text, new_agent_text_message
from pydantic import ValidationError

from src.a2a_adapter.models import EvalRequest, EvalResult
from src.green_agent.core import GreenHealthcareAgent

logger = logging.getLogger(__name__)

TASK_NAME_MAPPING = {
    "task1": "Patient Search",
    "task2": "Age Calculation",
    "task3": "Vital Sign Recording",
    "task4": "Lab Result Retrieval",
    "task5": "Medication Ordering",
    "task6": "Data Summarization",
    "task7": "Most Recent Value",
    "task8": "Procedure Ordering",
    "task9": "Medication + Schedule",
    "task10": "Lab Gap Closure"
}

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
        start_time = time.time()

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
                # If specifically requested IDs are missing, that's a reject error
                # But for robustness, maybe we just want to warn?
                # Let's reject for now if nothing matches explicit list.
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
        passed_count = 0
        failed_tasks = []

        for i, task in enumerate(tasks_to_run):
            task_id = task.get("id", "unknown")
            # Derive task type (e.g. task1_1 -> task1)
            task_type = task_id.split('_')[0] if "_" in task_id else "unknown"
            task_name = TASK_NAME_MAPPING.get(task_type, f"Type: {task_type}")

            await updater.update_status(TaskState.working, new_agent_text_message(f"[{i+1}/{total_tasks}] Selected Task: {task_id}"))

            try:
                 result = await self.agent.run_assessment(task, participants, updater, interaction_limit=interaction_limit)
            except Exception as e:
                 logger.exception(f"Assessment execution failed for task {task_id}")
                 
                 # CRITICAL FIX: Do NOT send TaskState.failed, as it kills the client.
                 # Send TaskState.working with error info and continue.
                 await updater.update_status(TaskState.working, new_agent_text_message(f"Execution error for {task_id}: {e}. Skipping..."))
                 
                 failed_tasks.append({
                    "task_id": task_id,
                    "task_type": task_type,
                    "task_name": task_name,
                    "feedback": f"System Error: {str(e)}",
                    "score": 0.0
                 })
                 continue

            # 4. Final Artifact per task
            # Ensure strict adherence to agentbeats-tutorial artifact schema
            
            # Derive task type (e.g. task1_1 -> task1)
            task_type = task_id.split('_')[0] if "_" in task_id else "unknown"
            task_name = TASK_NAME_MAPPING.get(task_type, f"Type: {task_type}")

            artifact_content = {
                "score": result.score,
                "feedback": result.feedback,
                "task_id": result.task_id,
                "task_type": task_type,
                "task_name": task_name,
                "metadata": result.metadata,
                "artifact_type": "result" 
            }
            
            # Add timestamp if not present
            if "timestamp" not in artifact_content:
                artifact_content["timestamp"] = datetime.now(timezone.utc).isoformat()
    
            logger.info(f"Assessment complete for {task_id} ({task_name}). Score: {result.score}")
            
            # Update counters
            if result.score == 1.0:
                passed_count += 1
            else:
                failed_tasks.append({
                    "task_id": task_id,
                    "task_type": task_type,
                    "task_name": task_name,
                    "feedback": result.feedback,
                    "score": result.score
                })

            await updater.add_artifact(
                parts=[
                    Part(root=TextPart(text=f"Task: {task['instruction']}\nName: {task_name}\nGrade: {result.feedback}\nScore: {result.score}")),
                    Part(root=DataPart(data=artifact_content))
                ],
                name=f"evaluation_result_{task_id}", # Unique name per task
            )
        
        # 5. Final Summary Artifact
        summary_text = f"Total Score: {passed_count}/{total_tasks}\n"
        if failed_tasks:
            summary_text += f"\nFailed Tasks ({len(failed_tasks)}):\n"
            for ft in failed_tasks:
                summary_text += f"- {ft['task_id']} ({ft['task_name']}): {ft['feedback']}\n"
        else:
            summary_text += "\nAll tasks passed!"

        summary_content = {
            "total_tasks": total_tasks,
            "passed_tasks": passed_count,
            "failed_tasks": failed_tasks, # Now contains dicts with type info
            "score_summary": f"{passed_count}/{total_tasks}",
            "artifact_type": "evaluation_summary",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        logger.info(f"Assessment Group Complete. {summary_text}")

        await updater.add_artifact(
            parts=[
                Part(root=TextPart(text=summary_text)),
                Part(root=DataPart(data=summary_content))
            ],
            name="evaluation_summary",
        )

        await updater.update_status(TaskState.completed, new_agent_text_message("Assessment Complete"))
