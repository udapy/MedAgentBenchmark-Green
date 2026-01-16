import logging
import random
import re
import json
import asyncio
import os
import requests
from typing import Dict, Optional, Any, List

from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart
from a2a.utils import new_agent_text_message
from pydantic import HttpUrl

from src.a2a_adapter.models import EvalResult

try:
    import med_data.eval as evaluator
except ImportError:
    # Fallback if specific src path is needed or relative import
    # Assuming med_data is eventually moved or in pythonpath
    try:
        import src.med_data.eval as evaluator
    except ImportError:
        # Last resort for local testing structure
        import sys
        sys.path.append(os.getcwd())
        import src.med_data.eval as evaluator

# Import Messenger locally or from shared utils if we move it
# For now, let's assume Messenger needs to be adapted or used as is.
from src.messenger import Messenger

logger = logging.getLogger(__name__)

class GreenHealthcareAgent:
    def __init__(self):
        self.messenger = Messenger()
        
        # Prefer FHIR_BASE_URL, fallback to FHIR_SERVER_URL + /fhir, then localhost
        base = os.getenv("FHIR_BASE_URL")
        if not base:
            server = os.getenv("FHIR_SERVER_URL")
            if server:
                 base = f"{server.rstrip('/')}/fhir"
            else:
                 base = "http://localhost:8080/fhir"
        
        self.fhir_base_url = base
        self.tasks = []
        self._data_loaded = False

    async def initialize(self):
        """Async initialization (e.g. check FHIR, load data)."""
        await self._ensure_fhir_ready()
        if not self._data_loaded:
            self._load_data()

    async def _ensure_fhir_ready(self):
        if os.getenv("SKIP_FHIR_CHECK"):
            logger.info("Skipping FHIR server check.")
            return

        logger.info(f"Checking FHIR server status at {self.fhir_base_url}...")
        # Increase to 30 attempts x 2s = 60s, or loop until timeout env var
        max_retries = int(os.getenv("FHIR_CHECK_RETRIES", "30"))
        
        for i in range(max_retries): 
            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(None, lambda: requests.get(f"{self.fhir_base_url}/metadata", timeout=2))
                if response.status_code == 200:
                    logger.info("FHIR Server is UP!")
                    return
            except Exception:
                pass
            await asyncio.sleep(2)
        logger.warning("FHIR Server check failed or timed out. Proceeding anyway (might fail later).")

    def _load_data(self):
        path = "src/med_data/tasks.json"
        if not os.path.exists(path):
            # Try alternative path
            path = "med_data/tasks.json"
            
        try:
            with open(path, "r") as f:
                self.tasks = json.load(f)
            self._data_loaded = True
        except Exception as e:
            logger.error(f"Failed to load tasks from {path}: {e}")
            self.tasks = []

    def select_task(self, task_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self.tasks:
            return None
        
        if task_id:
            matches = [t for t in self.tasks if t.get("id") == task_id]
            return matches[0] if matches else None
        return random.choice(self.tasks)

    async def run_assessment(self, task: Dict[str, Any], participants: Dict[str, HttpUrl], updater: TaskUpdater, interaction_limit: int = 8) -> EvalResult:
        """
        Orchestrates the specific assessment logic.
        """
        target_role = next(iter(participants))
        target_url = str(participants[target_role])
        task_id = task.get("id", "unknown")

        # Prepare Payload
        # Use a service name 'green-agent' or customizable host for FHIR callbacks
        # If running in Docker compose as 'green-agent', this is fine.
        fhir_callback_host = os.getenv("FHIR_CALLBACK_HOST", "green-agent")
        fhir_url = f"http://{fhir_callback_host}:8080/fhir"

        payload = {
            "instruction": task["instruction"],
            "system_context": task["context"],
            "fhir_base_url": fhir_url,
            "interaction_limit": interaction_limit
        }

        # Send to Purple Agent
        await updater.update_status(TaskState.working, new_agent_text_message(f"Sending Task {task_id} to {target_role}"))
        
        try:
            # === HEARTBEAT IMPLEMENTATION ===
            # Create the task for talking to the agent
            talk_task = asyncio.create_task(
                self.messenger.talk_to_agent(json.dumps(payload), target_url)
            )
            
            # Wait for result or keep sending heartbeats
            start_time = asyncio.get_running_loop().time()
            while not talk_task.done():
                try:
                    # Wait up to 30 seconds for the task to complete
                    await asyncio.wait_for(asyncio.shield(talk_task), timeout=30.0)
                except asyncio.TimeoutError:
                    # If timeout occurs, it means 30s passed and task is still running.
                    # Send a heartbeat/keep-alive update to the client.
                    elapsed = int(asyncio.get_running_loop().time() - start_time)
                    logger.info(f"Waiting for agent response... ({elapsed}s elapsed)")
                    await updater.update_status(
                        TaskState.working, 
                        new_agent_text_message(f"Waiting for {target_role}... ({elapsed}s elapsed)")
                    )

            # Get the result (this will raise exception if talk_task failed)
            agent_response_text = await talk_task
            # =================================
            
        except Exception as e:
             raise RuntimeError(f"Communication failed: {e}")

        # Grade
        logger.info("Grading response...")
        await updater.update_status(TaskState.working, new_agent_text_message("Grading response..."))
        clean_resp = self._clean_response(agent_response_text)
        
        score, feedback = self._grade_submission(task, clean_resp)

        return EvalResult(
            score=score,
            feedback=feedback,
            task_id=task_id,
            metadata={
                "raw_response": clean_resp,
                "patient_id": task.get("patient_id", "unknown")
            }
        )

    def _clean_response(self, text: str) -> str:
        clean = text.strip()
        if "```" in clean:
             clean = clean.replace("```json", "").replace("```", "").strip()
        return clean


    def _grade_submission(self, task, submission_text) -> tuple[float, str]:
        # Mimic legacy eval logic
        # Extract content from "FINISH(...)"
        submission_content = submission_text
        if submission_text.startswith("FINISH(") and submission_text.endswith(")"):
            submission_content = submission_text[7:-1]
            
        # --- FIX: ROBUST EXTRACTION FOR TASK 1 (Patient Search) ---
        task_id = task.get("id", "")
        if task_id.startswith("task1"):
             # Look for S followed by 7 digits
             match = re.search(r"\b(S\d{7})\b", submission_content)
             if match:
                 # Reformat as JSON list for the strict evaluator
                 extracted_mrn = match.group(1)
                 logger.info(f"Extracted MRN {extracted_mrn} from response for {task_id}")
                 submission_content = json.dumps([extracted_mrn])
        # ----------------------------------------------------------
            
        # Create Stub for Evaluator
        class TaskOutputStub:
            def __init__(self, res):
                self.result = res
                self.history = []
        
        mock_output = TaskOutputStub(submission_content)
        
        try:
            # Use strict boolean evaluation (1.0 or 0.0)
            is_correct = evaluator.eval(task, mock_output, self.fhir_base_url)
            if is_correct:
                return 1.0, "Correct"
            return 0.0, "Incorrect"
        except Exception as e:
            return 0.0, f"Grading Error: {e}"
