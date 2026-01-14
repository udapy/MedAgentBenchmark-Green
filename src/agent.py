from typing import Any
import random
import json
import time
import requests
import asyncio
import os
import yaml
from pydantic import BaseModel, HttpUrl, ValidationError
from a2a.server.tasks import TaskUpdater
from a2a.types import Message, TaskState, Part, TextPart, DataPart
from a2a.utils import get_message_text, new_agent_text_message
from messenger import Messenger
try:
    import med_data.eval as evaluator
    from med_data.utils import verify_fhir_server
except ImportError:
    # Fallback if src is not in path but running from root
    import src.med_data.eval as evaluator
    from src.med_data.utils import verify_fhir_server

class EvalRequest(BaseModel):
    """Request format sent by the AgentBeats platform to green agents."""
    participants: dict[str, HttpUrl] # role -> agent URL
    config: dict[str, Any]

class Agent:
    required_roles: list[str] = ["purple_agent"]
    required_config_keys: list[str] = []

    async def _ensure_fhir_ready(self):
        """Waits for the FHIR server to be available (async)."""
        if self.config.get("fhir", {}).get("skip_check", False) or os.getenv("SKIP_FHIR_CHECK"):
            print("Skipping FHIR server check (SKIP_FHIR_CHECK set).")
            return

        # Only check once per agent lifecycle if needed, or every request if stateless?
        # A simple check is fast if it's up.
        print("Checking FHIR server status...")
        try:
             # Basic retry loop
            for i in range(120): # ~2 minutes max
                try:
                    # Run sync request in executor to avoid blocking loop
                    loop = asyncio.get_event_loop()
                    response = await loop.run_in_executor(None, lambda: requests.get(f"{self.fhir_base_url}/metadata", timeout=2))
                    
                    if response.status_code == 200:
                        print("FHIR Server is UP!")
                        return
                except requests.RequestException:
                    pass
                await asyncio.sleep(1)
            print("WARNING: FHIR Server did not start in time.")
        except Exception as e:
            print(f"Error checking FHIR status: {e}")

    def _load_data(self):
        """Loads tasks and logic."""
        try:
            # Try finding tasks.json in probable locations
            paths = ["src/med_data/tasks.json", "med_data/tasks.json", "../med_data/tasks.json"]
            found = False
            for p in paths:
                 if os.path.exists(p):
                     try:
                        with open(p, "r") as f:
                            self.tasks = json.load(f)
                        found = True
                        break
                     except Exception as e:
                         print(f"Error loading tasks from {p}: {e}")
            
            if not found:
                 print("Warning: tasks.json not found in expected paths.")
                 self.tasks = []
        except Exception as e:
            print(f"Failed to load tasks: {e}")
            self.tasks = []

    def __init__(self):
        self.messenger = Messenger()
    def _load_config(self):
        """Loads configuration from yaml file."""
        config_path = os.getenv("AGENT_CONFIG_PATH", "config/agent.config.yaml")
        if not os.path.exists(config_path):
            # Fallback for running from src or tests
            if os.path.exists("../config/agent.config.yaml"):
                config_path = "../config/agent.config.yaml"
        
        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    self.config = yaml.safe_load(f)
            except Exception as e:
                print(f"Error loading config from {config_path}: {e}")
                self.config = {}
        else:
            print(f"Warning: Config file not found at {config_path}")
            self.config = {}

    def __init__(self):
        self.messenger = Messenger()
        self._load_config()
        
        # Priority: Env Var > Config > Default
        env_fhir = os.getenv("FHIR_BASE_URL")
        config_fhir = self.config.get("fhir", {}).get("base_url")
        default_fhir = "http://localhost:8080/fhir"
        
        self.fhir_base_url = env_fhir or config_fhir or default_fhir
        
        self._load_data()
        
    # Old synchronous wait (removed/replaced)
    # def _wait_for_fhir(self): ...

    def validate_request(self, request: EvalRequest) -> tuple[bool, str]:
        # Loosen validation to accept any role if not strictly "purple_agent" but usually it is.
        # Use first participant if specific role not found?
        # For now, stricter:
        # missing_roles = set(self.required_roles) - set(request.participants.keys())
        # if missing_roles:
        #     return False, f"Missing roles: {missing_roles}"
        # actually, let's just use the first available agent if role is mismatch, or strict.
        # The prompt says "Purple Agent".
        return True, "ok"

    async def run(self, message: Message, updater: TaskUpdater) -> None:
        await self._ensure_fhir_ready()

        input_text = get_message_text(message)
        try:
            request: EvalRequest = EvalRequest.model_validate_json(input_text)
            ok, msg = self.validate_request(request)
            if not ok:
                await updater.reject(new_agent_text_message(msg))
                return
        except ValidationError as e:
            await updater.reject(new_agent_text_message(f"Invalid request: {e}"))
            return

        # Get Purple Agent URL
        # Assumption: There is one participant.
        if not request.participants:
             await updater.reject(new_agent_text_message("No participants provided."))
             return
        
        target_role = next(iter(request.participants))
        target_url = str(request.participants[target_role])

        await updater.update_status(TaskState.working, new_agent_text_message("Generating MedAgentBench Task..."))

        # Select a task
        if not self.tasks:
            await updater.reject(new_agent_text_message("No tasks available in MedAgentBench."))
            return
            
        # Allow forcing a specific task via config for testing/verification
        force_id = request.config.get("force_task_id")
        if force_id:
            # Find task by ID
            matches = [t for t in self.tasks if t.get("id") == force_id]
            if matches:
                 task = matches[0]
            else:
                 await updater.reject(new_agent_text_message(f"Task ID {force_id} not found."))
                 return
        else:
            task = random.choice(self.tasks)
            
        task_id = task.get("id", "unknown")
        
        # Construct Payload
        # Note: Green Agent hostname should be used for FHIR URL if external access is needed.
        # Within the cluster/network, 'medagent-green' or similar might be the name.
        # But the prompt says: "fhir_base_url": "http://green-agent:8080/fhir"
        # Since we don't know the exact hostname of THIS container from the outside (depends on docker-compose),
        # but the prompt explicitly said to use `green-agent`, I'll use that.
        # Or I can try to detect it, but `green-agent` is a safe convention if defined in the prompt.
        
        payload = {
            "instruction": task["instruction"],
            "system_context": task["context"],
            "fhir_base_url": "http://green-agent:8080/fhir", # As per prompt, or could use self.fhir_base_url if accessible
            "interaction_limit": 8
        }

        await updater.update_status(TaskState.working, new_agent_text_message(f"Sending Task ID: {task_id}"))

        # Send to Purple Agent
        try:
            # We expect a text response "FINISH([...])" or just the answer? 
            # The prompt says: Purple Agent sends `finish([answer_string])`.
            # But talk_to_agent returns a Message object.
            agent_response_text = await self.messenger.talk_to_agent(
                json.dumps(payload), 
                target_url
            )
            # agent_response_text = get_message_text(agent_response_msg) # Removed: talk_to_agent returns str
        except Exception as e:
            await updater.update_status(TaskState.failed, new_agent_text_message(f"Communication failed: {e}"))
            return

        # Grade Result
        await updater.update_status(TaskState.working, new_agent_text_message("Grading response..."))
        
        # Parse the response to get the inner answer.
        # The prompt says: Purple Agent sends `finish([answer_string])`
        # We need to extract the answer list.
        # Logic adapted from legacy __init__.py `r.startswith('FINISH(')`
        
        clean_resp = agent_response_text.strip()
        # Handle markdown code blocks
        if "```" in clean_resp:
             clean_resp = clean_resp.replace("```json", "").replace("```", "").strip()

        # Simple parsing logic
        result_list = []
        if clean_resp.startswith("FINISH(") and clean_resp.endswith(")"):
            inner = clean_resp[7:-1]
            try:
                # Use json.loads to safely parse the list if it's valid JSON format inside
                # But it might be python list string. 
                # Legacy code used `r[len('FINISH('):-1]` which returns a string representation of list?
                # Actually legacy sends `result=r` to eval.
                # Let's check how eval expects it.
                # eval.py calls `grader_func(case_data, results, ...)`
                # results is TaskOutput, containing result.
                # If we mimic the object structure or just pass what grader_func expects.
                # Wait, eval.py imports refsol and calls `grader_func = getattr(refsol, task_id)`.
                # We need to see what `grader_func` signature is.
                # `eval(self.data[index], results[i], self.fhir_api_base)`
                # results[i] is a TaskOutput object.
                pass
            except:
                pass
        
        # Since I don't have the real refsol, I'm using a placeholder.
        # I'll create a Mock object for results to pass to eval
        
        class MockResult:
            def __init__(self, content):
                self.result = content # This is the "FINISH(...)" string or the list?
                # Legacy: `result` in TaskOutput was `r[len('FINISH('):-1]` i.e. content of finish.
                # So if input is FINISH(["foo"]), result is ["foo"] (string representation) or list object?
                # In legacy __init__.py: `result=r[len('FINISH('):-1]` -> "['answer']" string?
                # Then `eval.py` passes this TaskOutput to refsol.
                pass
        
        # Extracting the actual answer content
        if clean_resp.startswith("FINISH("):
             submission = clean_resp[7:-1] # String inside parens
        else:
             submission = clean_resp # Fallback

        # Create a mock result object that matches what legacy evaluator expects (attribute access)
        class TaskOutputStub:
            def __init__(self, res):
                self.result = res
        
        mock_task_output = TaskOutputStub(submission)
        
        score = 0.0
        feedback = "Incorrect"
        
        try:
            # Use the local evaluator which imports refsol (our stub)
            # We need to ensure we pass the right arguments.
            # case_data = task
            # results = mock_task_output
            # fhir_api_base = self.fhir_base_url
            
            # Note: our local eval.py imports refsol. 
            # Ensure src.med_data.eval works.
            is_correct = evaluator.eval(task, mock_task_output, self.fhir_base_url)
            
            if is_correct:
                score = 1.0
                feedback = "Correct"
            else:
                score = 0.0
                feedback = "Incorrect"
                
        except Exception as e:
            feedback = f"Grading error: {e}"
            score = 0.0

        await updater.add_artifact(
            parts=[
                Part(root=TextPart(text=f"Task: {task['instruction']}\nResult: {clean_resp}\nGrade: {feedback}")),
                Part(root=DataPart(data={
                    "score": score,
                    "feedback": feedback,
                    "task_id": task_id
                }))
            ],
            name="MedAgentBench Assessment",
        )
