import sys
import os
import json
import importlib
from typing import Any
from dataclasses import dataclass

# Ensure src is in path
sys.path.append(os.path.abspath("src"))

try:
    from src.med_data import eval as evaluator
except ImportError:
    # Fallback for different execution contexts
    try:
        from med_data import eval as evaluator
    except ImportError:
        print("Error: Could not import evaluator. Make sure you are running from the project root.")
        sys.exit(1)

# ANSI Colors
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

@dataclass
class MockResult:
    result: str
    history: list = None

    def __post_init__(self):
        if self.history is None:
            self.history = []

def load_tasks_from_file(filepath="src/med_data/tasks.json"):
    """Loads tasks from the given JSON file."""
    if not os.path.exists(filepath):
        print(f"{Colors.RED}Error: Task file not found at {filepath}{Colors.ENDC}")
        return []
    
    with open(filepath, 'r') as f:
        return json.load(f)

def get_task_by_id(tasks, task_id):
    """Finds a task by its ID."""
    for task in tasks:
        if task.get("id") == task_id:
            return task
    return None

def verify_task(task_id: str, tasks: list):
    """
    Runs the verification logic for a specific task.
    1. Loads the task.
    2. Simulates a CORRECT answer (derived from task['sol']).
    3. Simulates an INCORRECT answer.
    4. Evaluates both using the official src.med_data.eval logic.
    5. Prints a visualization table.
    """
    task = get_task_by_id(tasks, task_id)
    if not task:
        print(f"{Colors.RED}Task {task_id} not found.{Colors.ENDC}")
        return

    print(f"\n{Colors.HEADER}{Colors.BOLD}Evaluating Task: {task_id}{Colors.ENDC}")
    print(f"{Colors.CYAN}Instruction:{Colors.ENDC} {task.get('instruction')}")
    print(f"{Colors.CYAN}Expected Solution:{Colors.ENDC} {task.get('sol')}")
    print("-" * 60)

    # --- Test Case 1: Correct Answer ---
    # Note: Refsol often expects json dumped string
    correct_val = task.get('sol')
    
    # Adapt to how refsol expects input based on observation of verify_agent.py
    # Some tasks expect a list, some might expect the raw value if logic differs?
    # Based on verify_agent.py unittest: mock_result_correct.result = json.dumps(["Test Answer"])
    # So we assume json.dumps(list) is the standard format for the result string.
    
    correct_payload = json.dumps(correct_val)
    mock_correct = MockResult(result=correct_payload)
    
    # We need a mock FHIR URL
    fhir_base = "http://mock-fhir-server:8080/fhir/"
    
    # Run Eval for Correct
    print(f"{Colors.BLUE}Case 1: Simulating Correct Agent Response{Colors.ENDC}")
    print(f"   Payload: {correct_payload}")
    
    # We wrap the eval call to catch any implementation-specific errors (like missing network mocks if eval makes calls)
    try:
        # Note: Some eval tasks make real network calls! 
        # e.g. task2 calls send_get_request(url).
        # We need to mock send_get_request if we want this to be purely offline or specific tasks to run.
        # But user asked to "evaluate if it correct or not based on this benchmark evaluation metrix".
        # If the eval logic requires a live FHIR server, this script will fail without one unless valid mocks are in place.
        # However, for Task 1 (task1_X), the logic in refsol.py `task1` seems to ONLY check `ref_sol == json.loads(results.result)`.
        # It DOES NOT make network calls inside `task1` function in refsol.py (I read it in previous turn).
        # So Task 1 is safe to run without networking.
        
        is_pass_correct = evaluator.eval(task, mock_correct, fhir_base)
        status_c = f"{Colors.GREEN}PASS{Colors.ENDC}" if is_pass_correct else f"{Colors.RED}FAIL{Colors.ENDC}"
        print(f"   Result: {status_c}")
    except Exception as e:
        print(f"   {Colors.RED}Error during eval:{Colors.ENDC} {e}")

    # --- Test Case 2: Incorrect Answer ---
    incorrect_val = ["INCORRECT_VALUE_999"]
    incorrect_payload = json.dumps(incorrect_val)
    mock_incorrect = MockResult(result=incorrect_payload)

    print(f"\n{Colors.BLUE}Case 2: Simulating Incorrect Agent Response{Colors.ENDC}")
    print(f"   Payload: {incorrect_payload}")
    
    try:
        is_pass_incorrect = evaluator.eval(task, mock_incorrect, fhir_base)
        # For incorrect input, PASS means it correctly identified it as wrong? 
        # No, evaluator.eval returns True if the answer is CORRECT.
        # So we expect this to return False.
        
        if not is_pass_incorrect:
            status_i = f"{Colors.GREEN}PASS (Correctly Rejected){Colors.ENDC}"
        else:
            status_i = f"{Colors.RED}FAIL (Incorrectly Accepted){Colors.ENDC}"
            
        print(f"   Result: {status_i}")
    except Exception as e:
        print(f"   {Colors.RED}Error during eval:{Colors.ENDC} {e}")

    print("-" * 60)

def main():
    tasks = load_tasks_from_file()
    if not tasks:
        return

    # User asked for "one of actula task". Let's pick task1_1 as default.
    # We can also verify other tasks that don't pass network calls if needed.
    target_task = "task1_1" 
    
    # Check if user passed an arg
    if len(sys.argv) > 1:
        target_task = sys.argv[1]

    verify_task(target_task, tasks)

if __name__ == "__main__":
    main()
