#!/usr/bin/env python
"""
Script to trigger the RankAlpha pipeline DAG on startup.
This ensures data is fresh when the system starts.
"""

import time
import subprocess
import sys
from datetime import datetime

def wait_for_airflow():
    """Wait for Airflow to be ready."""
    max_attempts = 30
    attempt = 0
    
    while attempt < max_attempts:
        try:
            # Check if Airflow webserver is responding
            result = subprocess.run(
                ["airflow", "dags", "list"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and "rankalpha_pipeline" in result.stdout:
                print(f"Airflow is ready (attempt {attempt + 1})")
                return True
                
        except Exception as e:
            print(f"Waiting for Airflow... (attempt {attempt + 1}/{max_attempts})")
        
        time.sleep(10)
        attempt += 1
    
    print("Airflow did not become ready in time")
    return False

def trigger_dag():
    """Trigger the RankAlpha pipeline DAG."""
    try:
        # Trigger the DAG
        result = subprocess.run(
            ["airflow", "dags", "trigger", "rankalpha_pipeline", "--run-id", f"startup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            print(f"Successfully triggered rankalpha_pipeline DAG")
            print(result.stdout)
            return True
        else:
            print(f"Failed to trigger DAG: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"Error triggering DAG: {str(e)}")
        return False

def main():
    print(f"Starting DAG trigger script at {datetime.now()}")
    
    # Wait for Airflow to be ready
    if not wait_for_airflow():
        sys.exit(1)
    
    # Wait a bit more to ensure all services are ready
    print("Waiting 30 seconds for all services to stabilize...")
    time.sleep(30)
    
    # Trigger the DAG
    if trigger_dag():
        print("DAG triggered successfully")
        sys.exit(0)
    else:
        print("Failed to trigger DAG")
        sys.exit(1)

if __name__ == "__main__":
    main()