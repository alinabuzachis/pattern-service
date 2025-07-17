import contextlib
import io
import json
import logging
import os
import shutil
import tarfile
import tempfile
from typing import Iterator
from django.db import transaction

from requests import Session
from requests.auth import HTTPBasicAuth
from django.conf import settings

import requests

from .models import Pattern
from .models import PatternInstance
from .models import ControllerLabel
from .models import Task

logger = logging.getLogger(__name__)


def update_task_status(task: Task, status_: str, details: dict):
    task.status = status_
    task.details = details
    task.save()


@contextlib.contextmanager
def download_collection(url: str, collection: str, version: str) -> Iterator[str]:
    """
    Downloads and extracts a collection to a temporary path.
    Returns the path where files were extracted.
    """
    temp_base_dir = tempfile.mkdtemp()

    collection_path = os.path.join(temp_base_dir, f"{collection}-{version}")
    os.makedirs(collection_path, exist_ok=True)

    try:
        response = requests.get(url)
        response.raise_for_status()
        in_memory_tar = io.BytesIO(response.content)

        with tarfile.open(fileobj=in_memory_tar, mode="r|*") as tar:
            tar.extractall(path=collection_path, filter="data")

        logger.info(f"Collection extracted to {collection_path}")
        yield collection_path  # Yield the path to the caller
    finally:
        shutil.rmtree(temp_base_dir)


def get_http_session() -> Session:
    """Returns a session with Basic Auth for AAP."""
    session = Session()
    session.auth = HTTPBasicAuth(settings.AAP_USERNAME, settings.AAP_PASSWORD)
    session.verify = settings.AAP_VERIFY_SSL
    session.headers.update({'Content-Type': 'application/json'})

    return session

def post_api(path: str, data: dict) -> dict:
    session = get_http_session()
    response = session.post(f"{settings.AAP_URL.rstrip('/')}/api/v2{path}", json=data)
    response.raise_for_status()

    return response.json()


def get_api(path: str, params=None) -> dict:
    session = get_http_session()
    response = session.get(f"{settings.AAP_URL.rstrip('/')}/api/v2{path}", params=params)
    response.raise_for_status()

    return response.json()


def create_controller_project(instance: PatternInstance, pattern: Pattern, pattern_def: dict) -> int:
    """
    Creates a controller project on AAP using the pattern definition.

    Args:
        instance: The PatternInstance object.
        pattern: The related Pattern object.
        pattern_def: The pattern definition dictionary.

    Returns:
        The created project ID.
    """
    project_def = pattern_def["aap_resources"]["controller_project"]
    project_def.update({
        "organization": instance.organization_id,
        "scm_type": "archive",
        "scm_url": pattern.collection_version_uri,
        "credential": instance.credentials.get("project"),
    })
    logger.debug(f"Project definition: {project_def}")
    response = post_api("/projects/", project_def)

    return response["id"]


def create_execution_environment(instance: PatternInstance, pattern_def: dict) -> int:
    """
    Creates an execution environment for the controller.

    Args:
        instance: The PatternInstance object.
        pattern_def: The pattern definition dictionary.

    Returns:
        The created execution environment ID.
    """
    ee_def = pattern_def["aap_resources"]["controller_execution_environment"]
    image_name = ee_def.pop("image_name")
    ee_def.update({
        "organization": instance.organization_id,
        "credential": instance.credentials.get("ee"),
        "image": f"{urllib.parse.urlparse(settings.AAP_URL).netloc}/{image_name}",
        "pull": ee_def.get("pull") or "missing",
    })
    logger.debug(f"EE definition: {ee_def}")
    return client.create_controller_ee(ee_def)


def create_labels(instance: PatternInstance, pattern_def: dict) -> List[ControllerLabel]:
    """
    Creates controller labels and returns model instances.

    Args:
        instance: The PatternInstance object.
        pattern_def: The pattern definition dictionary.

    Returns:
        List of ControllerLabel model instances.
    """
    labels = []
    for name in pattern_def["aap_resources"]["controller_labels"]:
        label_def = {"name": name, "organization": instance.organization_id}
        logger.debug(f"Label definition: {label_def}")
        label_id = client.create_controller_label(label_def)
        label_obj, _ = ControllerLabel.objects.get_or_create(label_id=label_id)
        labels.append(label_obj)
    return labels


def create_job_templates(
    instance: PatternInstance,
    pattern_def: dict,
    project_id: int,
    ee_id: int
) -> List[Dict[str, Any]]:
    """
    Creates job templates and associated surveys.

    Args:
        instance: The PatternInstance object.
        pattern_def: The pattern definition dictionary.
        project_id: Controller project ID.
        ee_id: Execution environment ID.

    Returns:
        List of dictionaries describing created automations.
    """
    automations = []
    for jt in pattern_def["aap_resources"]["controller_job_templates"]:
        survey = jt.pop("survey", None)
        primary = jt.pop("primary", False)
        jt.update({
            "organization": instance.organization_id,
            "project": project_id,
            "execution_environment": ee_id,
            "playbook": f"extensions/patterns/{pattern_def['name']}/playbooks/{jt['playbook']}",
            "ask_inventory_on_launch": True,
        })
        logger.debug(f"Job template: {jt}")
        jt_id = client.create_controller_job_template(jt)
        if survey:
            client.create_controller_job_template_survey(jt_id, survey)
        automations.append({"type": "job_template", "id": jt_id, "primary": primary})
    return automations


def save_instance_state(
    instance: PatternInstance,
    project_id: int,
    ee_id: int,
    labels: List[ControllerLabel],
    automations: List[Dict[str, Any]]
) -> None:
    """
    Saves the instance and links labels and automations inside a DB transaction.

    Args:
        instance: The PatternInstance to update.
        project_id: Controller project ID.
        ee_id: Execution environment ID.
        labels: List of ControllerLabel objects.
        automations: List of job template metadata.
    """
    with transaction.atomic():
        instance.controller_project_id = project_id
        instance.controller_execution_environment_id = ee_id
        instance.save()
        for label in labels:
            instance.controller_labels.add(label)
        for auto in automations:
            instance.automations.create(
                automation_type=auto["type"],
                automation_id=auto["id"],
                primary=auto["primary"],
            )


def assign_execute_roles(
    executors: Dict[str, List[Any]],
    automations: List[Dict[str, Any]]
) -> None:
    """
    Assigns JobTemplate Execute role to teams and users.

    Args:
        executors: Dictionary with "teams" and "users" lists.
        automations: List of job template metadata.
    """
    if not executors["teams"] and not executors["users"]:
        return
    role_id = client.get_role_definition_id("JobTemplate Execute")
    for auto in automations:
        for team in executors["teams"]:
            client.create_controller_role_assignment("team", auto["id"], role_id, str(team))
        for user in executors["users"]:
            client.create_controller_role_assignment("user", auto["id"], role_id, str(user))


def run_pattern_task(pattern_id: int, task_id: int):
    """
    Orchestrates downloading a collection and saving a pattern definition.
    """
    task = Task.objects.get(id=task_id)

    try:
        pattern = Pattern.objects.get(id=pattern_id)
        update_task_status(task, "Running", {"info": "Processing pattern"})

        # Skip download if URI is missing
        if not pattern.collection_version_uri:
            update_task_status(task, "Completed", {"info": "Pattern saved without external definition"})
            return

        update_task_status(task, "Running", {"info": "Downloading collection tarball"})

        # Get all necessary names from the pattern object
        collection_name = pattern.collection_name.replace(".", "-")
        collection_version = pattern.collection_version
        pattern_name = pattern.pattern_name

        with download_collection(pattern.collection_version_uri, collection_name, collection_version) as collection_path:
            path_to_definition = os.path.join(collection_path, "extensions", "patterns", pattern_name, "meta", "pattern.json")

            with open(path_to_definition, "r") as file:
                definition = json.load(file)

            pattern.pattern_definition = definition
            pattern.save()

        update_task_status(task, "Completed", {"info": "Pattern processed successfully"})

    except FileNotFoundError:
        logger.error(f"Could not find pattern definition for task {task_id}")
        update_task_status(task, "Failed", {"error": "Pattern definition file not found in collection."})

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        update_task_status(task, "Failed", {"error": str(e)})


def run_pattern_instance_task(instance_id: int, task_id: int):
    task = Task.objects.get(id=task_id)

    try:
        instance = PatternInstance.objects.select_related("pattern").get(id=instance_id)
        pattern = instance.pattern
        pattern_def = pattern.pattern_definition or {}

        update_task_status(task, "Running", {"info": "Processing PatternInstance"})

        if not pattern_def:
            raise ValueError("Pattern definition is missing.")

        update_task_status(task, "Running", {"info": "Creating controller project"})
        project_id = create_controller_project(instance, pattern, pattern_def)

        update_task_status(task, "Running", {"info": "Creating execution environment"})
        ee_id = create_execution_environment(instance, pattern_def)

        update_task_status(task, "Running", {"info": "Creating controller labels"})
        labels = create_labels(instance, pattern_def)

        update_task_status(task, "Running", {"info": "Creating job templates"})
        automations = create_job_templates(instance, pattern_def, project_id, ee_id)

        update_task_status(task, "Running", {"info": "Saving instance and related objects"})
        save_instance_state(instance, project_id, ee_id, labels, automations)

        update_task_status(task, "Running", {"info": "Assigning executor roles"})
        assign_execute_roles(instance.executors, automations)

        update_task_status(task, "Completed", {"info": "PatternInstance processed"})
    except Exception as e:
        logger.exception("Failed to process PatternInstance.")
        update_task_status(task, "Failed", {"error": str(e)})
