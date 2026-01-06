
import os
import sys
import logging
import subprocess
import uuid
from typing import Optional

from google.cloud import run_v2
from google.api_core.client_options import ClientOptions

from app.config import get_settings

logger = logging.getLogger(__name__)

def run_ingestion_job(job_id: uuid.UUID) -> None:
    """
    Triggers the ingestion worker for a specific job.
    Supports 'local' (subprocess) and 'cloudrun' (Cloud Run Jobs) modes.
    """
    settings = get_settings()
    job_id_str = str(job_id)

    if settings.JOB_RUNNER_MODE == "local":
        _run_local(job_id_str, settings.WORKER_PATH)
    elif settings.JOB_RUNNER_MODE == "cloudtasks":
        _enqueue_cloud_task(job_id_str, settings)
    else:
        logger.warning(f"Unknown JOB_RUNNER_MODE '{settings.JOB_RUNNER_MODE}'. Job {job_id} not triggered.")

def _run_local(job_id: str, worker_path: str):
    """
    Runs the worker script locally in a subprocess.
    """
    try:
        # Use simple Popen to run in background (fire-and-forget from API perspective)
        # Inherit env vars and add JOB_ID
        env = os.environ.copy()
        env["JOB_ID"] = job_id
        
        # Determine strict path to worker.py if needed, or assume CWD
        # worker_path default is "worker.py"
        
        # Using sys.executable ensures we use the same python interpreter (venv)
        cmd = [sys.executable, worker_path]
        
        subprocess.Popen(cmd, env=env)
        logger.info(f"Triggered local worker for Job {job_id}")
        
    except Exception as e:
        logger.error(f"Failed to trigger local worker for Job {job_id}: {e}")

def _run_cloud_run_job(job_id: str, settings):
    """
    Triggers a Cloud Run Job execution.
    """
    if not settings.GCP_PROJECT_ID or not settings.GCP_REGION or not settings.CLOUD_RUN_JOB_NAME:
        logger.error("Missing GCP configuration for Cloud Run Job trigger.")
        return

    check_msg = (
        f"Triggering Cloud Run Job '{settings.CLOUD_RUN_JOB_NAME}' "
        f"in {settings.GCP_REGION} for Job {job_id}"
    )
    logger.info(check_msg)

    try:
        # Client Options for specific region
        client_options = ClientOptions(
            api_endpoint=f"{settings.GCP_REGION}-run.googleapis.com"
        )
        client = run_v2.JobsClient(client_options=client_options)

        # Release Client (job_path usage)
        # We need to get the job to find the container name to ensure we override the correct one
        # (especially with Cloud SQL sidecars potentially present)
        
        # Build Job Name Path
        name = client.job_path(
            settings.GCP_PROJECT_ID, 
            settings.GCP_REGION, 
            settings.CLOUD_RUN_JOB_NAME
        )
        
        # 1. Get Job Definition
        job_obj = client.get_job(name=name)
        
        # Assuming the user code is in the first container of the template
        # or we find the one that is NOT the cloud-sql-proxy if feasible
        # Usually the user container is the first one defined in 'containers' list logic
        container_name = job_obj.template.template.containers[0].name
        
        logger.info(f"Targeting container '{container_name}' for override.")

        # Override Env Var JOB_ID
        overrides = run_v2.RunJobRequest.Overrides(
            container_overrides=[
                run_v2.RunJobRequest.Overrides.ContainerOverride(
                    name=container_name,
                    env=[
                        run_v2.EnvVar(name="JOB_ID", value=job_id)
                    ]
                )
            ]
        )

        request = run_v2.RunJobRequest(
            name=name,
            overrides=overrides
        )

        # Run Job (Async operation, but we don't wait for completion)
        operation = client.run_job(request=request)
        
        logger.info(f"Cloud Run Job triggered successfully. Operation: {operation.operation.name}")
        
    except Exception as e:
        logger.error(f"Failed to trigger Cloud Run Job for {job_id}: {e}")

def _enqueue_cloud_task(job_id: str, settings):
    """
    Enqueues a task to the Cloud Tasks queue to trigger the worker service.
    """
    from google.cloud import tasks_v2
    import json

    if not all([settings.GCP_PROJECT_ID, settings.CLOUD_TASKS_LOCATION, settings.CLOUD_TASKS_QUEUE, settings.WORKER_SERVICE_URL]):
        logger.error("Missing Cloud Tasks configuration (Project, Location, Queue, or Worker URL).")
        return

    try:
        client = tasks_v2.CloudTasksClient()
        
        # Construct the fully qualified queue name
        parent = client.queue_path(settings.GCP_PROJECT_ID, settings.CLOUD_TASKS_LOCATION, settings.CLOUD_TASKS_QUEUE)
        
        # Construct the task payload
        task = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{settings.WORKER_SERVICE_URL}/internal/process",
                "headers": {"Content-Type": "application/json"},
                # Add OIDC token for authentication between services
                "oidc_token": {
                    "service_account_email": f"vision-run-sa@{settings.GCP_PROJECT_ID}.iam.gserviceaccount.com" # Assuming default SA pattern or configured one
                },
            }
        }
        
        # Add payload body
        payload = {"job_id": job_id}
        task["http_request"]["body"] = json.dumps(payload).encode()
        
        # Send the task
        response = client.create_task(request={"parent": parent, "task": task})
        
        logger.info(f"Enqueued Cloud Task: {response.name} for Job {job_id}")

    except Exception as e:
        logger.error(f"Failed to enqueue Cloud Task for Job {job_id}: {e}")
        # Log stack trace for debugging
        import traceback
        traceback.print_exc()
