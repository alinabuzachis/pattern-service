import asyncio
import io
import json
import logging
import os
import shutil
import tarfile
import tempfile
import urllib.parse

import aiohttp
from asgiref.sync import sync_to_async
from django.db import transaction

from .models import ControllerLabel
from .models import Pattern
from .models import PatternInstance
from .models import Task

logger = logging.getLogger(__name__)


async def update_task_status(task: Task, status_: str, details: dict):
    task.status = status_
    task.details = details
    await task.asave()


async def download_collection(url: str, collection: str, version: str) -> str:
    """
    Asynchronously downloads and extracts a collection to a path.
    Returns the path where files were extracted.
    """
    temp_base_dir = tempfile.mkdtemp()

    collection_path = os.path.join(temp_base_dir, f"{collection}-{version}")
    os.makedirs(collection_path, exist_ok=True)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                in_memory_tar = io.BytesIO(await resp.read())

        with tarfile.open(fileobj=in_memory_tar, mode="r|*") as tar:
            tar.extractall(path=collection_path, filter="data")

        logger.info(f"Collection extracted to {collection_path}")
        return collection_path  # Return the path, not its contents
    except Exception:
        # If anything fails, clean up the directory and re-raise the error
        shutil.rmtree(temp_base_dir)
        raise


async def run_pattern_instance_task(instance_id: int, task_id: int):
    task = await sync_to_async(Task.objects.get, thread_sensitive=True)(id=task_id)

    try:
        instance = await sync_to_async(PatternInstance.objects.select_related("pattern").get, thread_sensitive=True)(id=instance_id)
        pattern = instance.pattern

        # Make sure the Pattern has pattern_definition loaded (could be empty)
        pattern_def = pattern.pattern_definition or {}

        await update_task_status(task, "Running", {"info": "Processing PatternInstance"})

        if not pattern_def:
            raise Exception("Pattern definition is missing. Cannot process instance.")

        # Update instance fields with data from pattern definition inside transaction
        def update_instance():
            with transaction.atomic():
                if "execution_environment_id" in pattern_def:
                    instance.controller_ee_id = int(pattern_def["execution_environment_id"])
                if "executors" in pattern_def:
                    instance.executors = pattern_def["executors"]
                if "controller_labels" in pattern_def:
                    for label_id in pattern_def["controller_labels"]:
                        label_obj, _ = ControllerLabel.objects.get_or_create(label_id=label_id)
                        instance.controller_labels.add(label_obj)

                instance.controller_project_id = hash(pattern.pattern_name) % 10**6
                instance.save()

        await sync_to_async(update_instance, thread_sensitive=True)()

        await update_task_status(task, "Completed", {"info": "PatternInstance processed"})

async def run_pattern_task(pattern_id: int, task_id: int):
    task = await Task.objects.aget(id=task_id)
    collection_path = None

    try:
        pattern = await Pattern.objects.aget(id=pattern_id)
        await update_task_status(task, "Running", {"info": "Processing pattern"})

        # Skip download if URI is missing
        if not pattern.collection_version_uri:
            await update_task_status(task, "Completed", {"info": "Pattern saved without external definition"})
            return

        await update_task_status(task, "Running", {"info": "Downloading collection tarball"})

        # Get all necessary names from the pattern object
        collection_name = pattern.collection_name.replace(".", "-")
        collection_version = pattern.collection_version
        pattern_name = pattern.pattern_name

        collection_path = await download_collection(pattern.collection_version_uri, collection_name, collection_version)
        path_to_definition = os.path.join(collection_path, "extensions", "patterns", pattern_name, "meta", "pattern.json")
        with open(path_to_definition, "r") as file:
            definition = json.load(file)

        pattern.pattern_definition = definition
        await pattern.asave()
        await update_task_status(task, "Completed", {"info": "Pattern processed successfully"})
    except FileNotFoundError:
        logger.error(f"Could not find pattern definition for task {task_id}")
        await update_task_status(task, "Failed", {"error": "Pattern definition file not found in collection."})

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        await update_task_status(task, "Failed", {"error": str(e)})

    finally:
        if collection_path and os.path.exists(collection_path):
            shutil.rmtree(os.path.dirname(collection_path))
