import sys
import os
import time
from pathlib import Path

# Add repo root to path to import Sora2Get
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Inject mock_bin into PATH
mock_bin = os.path.abspath(os.path.join(os.path.dirname(__file__), "mock_bin"))
os.environ["PATH"] = mock_bin + os.pathsep + os.environ["PATH"]

# Set dummy env vars to avoid Side effects or errors
os.environ["QIITA_ITEM_ID"] = "dummy"
os.environ["AUTO_PASTE"] = "1"
os.environ["PASTE_DELAY_MS"] = "100"

import Sora2Get

def test_notify_perf():
    print("Testing notify performance...")
    start = time.time()
    Sora2Get.notify("123456")
    end = time.time()
    duration = end - start
    print(f"notify() took {duration:.4f} seconds")
    return duration

if __name__ == "__main__":
    # Clear log
    if os.path.exists("mock_log.txt"):
        os.remove("mock_log.txt")

    duration = test_notify_perf()

    # Check if mocks were called
    print("Waiting for background processes (if any)...")
    time.sleep(6) # Wait enough time for background threads/processes (total mock sleep is > 5s)

    if os.path.exists("mock_log.txt"):
        with open("mock_log.txt", "r") as f:
            content = f.read()
            print("Mock log content:")
            print(content)
            if "osascript called" in content and "afplay called" in content:
                 print("SUCCESS: Mock scripts were called.")
            else:
                 print("WARNING: Not all mock scripts were called.")
    else:
        print("Mock log not found! Subprocesses might not have run.")
