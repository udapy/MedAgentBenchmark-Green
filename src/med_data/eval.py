from .utils import *
import importlib

module_name = 'src.med_data.refsol'
try:
    refsol = importlib.import_module(module_name)
except ImportError:
    import src.med_data.refsol as refsol

def eval(case_data, results, fhir_api_base):
    task_id = case_data['id'].split('_')[0]
    try:
        if hasattr(refsol, task_id):
            grader_func = getattr(refsol, task_id)
            return grader_func(case_data, results, fhir_api_base)
        else:
            # Fallback for missing task implementation in stub
            # Check for a generic grader or return False/True based on policy
            if hasattr(refsol, 'placeholder_grade'):
                return refsol.placeholder_grade(case_data, results, fhir_api_base)
            print(f"No grader found for {task_id}")
            return False
    except Exception as e:
        print(f"Evaluation error: {e}")
        return False
