import datetime
import os
import json
import argparse
import concurrent.futures
import re
import subprocess
import threading
import openai
import time
import unittest
import shutil

def run_test(test_case):
    suite = unittest.TestSuite()
    suite.addTest(test_case)
    runner = unittest.TextTestRunner()
    result = runner.run(suite)
    return result.wasSuccessful()


suceess_tasks = 0
cout_tasks = 0
lock = threading.Lock()

def update_process(result):
    global suceess_tasks
    global cout_tasks

    lock.acquire()
    cout_tasks += 1
    if result:
        suceess_tasks += 1
    lock.release()

    return suceess_tasks, cout_tasks


def evaluate_task(api_key, api_base, model_engine, task_dir, output_dir):
    start_time = time.time()

    task_name = os.path.basename(task_dir)
    result_task_dir = os.path.join(output_dir, task_name)
    shutil.copytree(task_dir, result_task_dir)
    result_task_log = os.path.join(result_task_dir, "log.txt")
    result_task_report = os.path.join(result_task_dir, ".devchat.results.json")

    config_json = os.path.join(result_task_dir, ".meta", "config.json")
    with open(config_json, "r") as f:
        config = json.load(f)

    solution_py = os.path.join(result_task_dir, config["files"]["solution"][0])
    test_py = os.path.join(result_task_dir, config["files"]["test"][0])
    test_py_file = config["files"]["test"][0]

    instructions_md = os.path.join(result_task_dir, ".docs", "instructions.md")
    introduction_md = os.path.join(result_task_dir, ".docs", "introduction.md")
    instructions_append_md = os.path.join(result_task_dir, ".docs", "instructions.append.md")

    instructions = ""
    introduction = ""
    instructions_append = ""
    try:
        with open(instructions_md, "r") as f:
            instructions = f.read()
    except Exception:
        pass
    try:
        with open(introduction_md, "r") as f:
            introduction = f.read()
    except Exception:
        pass
    try:
        with open(instructions_append_md, "r") as f:
            instructions_append = f.read()
    except Exception:
        pass
    with open(solution_py, "r") as f:
        solution = f.read()
    with open(test_py, "r") as f:
        test = f.read()

    prompt = f"Task: Write a Python program that solves the following problem and passes the existing unit tests. The problem is described in the following documents:\n\nInstructions:\n{instructions}\n\nIntroduction:\n{introduction}\n\nInstructions Append:\n{instructions_append}\n\nHere is a skeleton that defines the required class and interface for the solution:\n\n{solution}\n\nAnd here are the existing unit tests:\n\n{test}\n\nPlease write your solution and include the required class and interface in your code. Make sure that your solution passes all the unit tests."


    def save_report(result, duration):
        nonlocal task_name
        nonlocal model_engine
        nonlocal result_task_report
        result_data = {
            "testcase": task_name,
            "model": model_engine,
            "tests_outcomes": [result],
            "duration": duration
        }
        with open(result_task_report, "w+", encoding="utf-8") as file:
            file.write(json.dumps(result_data, indent=4))
            file.write("\n")

    try:
        with open(result_task_log, "w+", encoding="utf-8") as file:
            try:
                client = openai.OpenAI(
                    api_key = api_key,
                    base_url = api_base
                )

                response = client.chat.completions.create(
                    model=model_engine,
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt}
                    ]
                )

                result = response.choices[0].message.content
                file.write(f"Receive: {result}")
                file.write("\n")

                code_block = re.search(r"```.*?\n(.*?)```", result, re.DOTALL)
                if code_block:
                    code = code_block.group(1)
                else:
                    code = result

                # Write the result to the solution file
                with open(solution_py, "w+") as f:
                    f.write(code)

                # Run the tests through the command line
                test_command = f"python -m unittest {test_py_file}"
                file.write(f"UnitTest command: {test_command}")
                file.write("\n")

                # run command with CWD as result_task_dir
                test_result = subprocess.run(test_command, shell=True, cwd=result_task_dir, capture_output=True, text=True)
                file.write(f"return code:{test_result.returncode}")
                file.write("\n")
                file.write(test_result.stdout)
                file.write("\n")
                file.write(test_result.stderr)
                file.write("\n")

                # Save the report
                save_report(test_result.returncode == 0, time.time()-start_time)
                v1, v2 = update_process(test_result.returncode == 0)
                print("task:", task_name, test_result.returncode == 0, f"{v1}/{v2}", time.time()-start_time)
                return test_result.returncode == 0, time.time()-start_time
            except Exception as err:
                file.write(f"Exception: {err}")
                file.write("\n")
                print("Exception:", err)
                save_report(False, time.time()-start_time)
                v1, v2 = update_process(False)
                print("task:", task_name, False, f"{v1}/{v2}", time.time()-start_time)
                return False, time.time()-start_time
    except Exception:
        save_report(False, time.time()-start_time)
        v1, v2 = update_process(False)
        print("task:", False, f"{v1}/{v2}", time.time()-start_time)
        return False, time.time()-start_time

class CustomFuture(concurrent.futures.Future):
    def __init__(self, task_dir):
        super().__init__()
        self.task_dir = task_dir

def evaluate_model(api_key, api_base, model_engine, task_dir, threads, output_dir):
    test_type = "pythoncode"
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    result_dir = f"{test_type}_benchmark_{timestamp}"
    result_dir = os.path.join(output_dir, result_dir)
    os.makedirs(result_dir, exist_ok=True)

    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        tasks = [subdir for subdir in os.listdir(task_dir) if os.path.isdir(os.path.join(task_dir, subdir)) and os.path.isdir(os.path.join(task_dir, subdir, ".docs"))]
        futures = [CustomFuture(os.path.join(task_dir, subdir)) for subdir in tasks]
        for future in futures:
            executor.submit(evaluate_task, api_key, api_base, model_engine, future.task_dir, result_dir).add_done_callback(future.set_result)
        results = [(future.task_dir, future.result().result()) for future in concurrent.futures.as_completed(futures)]
    return {"model": model_engine, "tasks": results}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-key", "--api_key", required=True, type=str, help="OpenAI API key")
    parser.add_argument("-base", "--base_url", required=True,  type=str, help="OpenAI API base url")
    parser.add_argument("-model", "--model", required=True, type=str, help="model engine")
    parser.add_argument("-task", "--task_dir", required=True, type=str, help="task directory")
    parser.add_argument("-threads", "--threads", type=int, help="threads num", default=1)
    parser.add_argument("-output", "--output_dir", required=True, type=str, help="result directory")
    args = parser.parse_args()

    api_key = args.api_key
    base_url = args.base_url
    model_engine = args.model
    task_dir = args.task_dir
    threads = args.threads
    output_dir = args.output_dir

    print("model:", model_engine)

    result = evaluate_model(api_key, base_url, model_engine, task_dir, threads, output_dir)
    print("-------------->>:")
    print(result)

if __name__ == "__main__":
    main()
