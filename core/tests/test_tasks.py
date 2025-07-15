from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Automation
from core.models import ControllerLabel
from core.models import Pattern
from core.models import PatternInstance
from core.models import Task
from core.tasks import run_pattern_instance_task
from core.tasks import run_pattern_task


class SharedDataMixin:
    @classmethod
    def setUpTestData(cls):
        cls.pattern = Pattern.objects.create(
            collection_name="mynamespace.mycollection",
            collection_version="1.0.0",
            collection_version_uri="https://example.com/mynamespace/mycollection/",
            pattern_name="example_pattern",
            pattern_definition={"key": "value"},
        )

        cls.pattern_instance = PatternInstance.objects.create(
            organization_id=1,
            controller_project_id=123,
            controller_ee_id=456,
            credentials={"user": "admin"},
            executors=[{"executor_type": "container"}],
            pattern=cls.pattern,
        )

        cls.label = ControllerLabel.objects.create(label_id=5)
        cls.pattern_instance.controller_labels.add(cls.label)

        cls.automation = Automation.objects.create(
            automation_type="job_template",
            automation_id=789,
            primary=True,
            pattern_instance=cls.pattern_instance,
        )

        cls.task = Task.objects.create(status="Running", details={"progress": "50%"})


class PatternInstanceViewSetTest(SharedDataMixin, APITestCase):
    def test_pattern_instance_list_view(self):
        url = reverse("patterninstance-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_pattern_instance_detail_view(self):
        url = reverse("patterninstance-detail", args=[self.pattern_instance.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["organization_id"], 1)

    @patch("core.views.async_to_sync")
    def test_pattern_instance_create_view(self, mock_async_to_sync):
        url = reverse("patterninstance-list")
        data = {
            "organization_id": 2,
            "controller_project_id": 0,
            "controller_ee_id": 0,
            "credentials": {"user": "tester"},
            "executors": [],
            "pattern": self.pattern.id,
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        instance = PatternInstance.objects.get(organization_id=2)
        self.assertIsNotNone(instance)

        task_id = response.data["task_id"]
        task = Task.objects.get(id=task_id)
        self.assertEqual(task.status, "Initiated")

        mock_async_to_sync.assert_called_once()
        self.assertIn("task_id", response.data)
        self.assertIn("message", response.data)


class AutomationViewSetTest(SharedDataMixin, APITestCase):
    def test_automation_list_view(self):
        url = reverse("automation-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_automation_detail_view(self):
        url = reverse("automation-detail", args=[self.automation.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["automation_type"], "job_template")


class ControllerLabelViewSetTest(SharedDataMixin, APITestCase):
    def test_label_list_view(self):
        url = reverse("controllerlabel-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_label_detail_view(self):
        url = reverse("controllerlabel-detail", args=[self.label.id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('id', response.data)
        self.assertIn('label_id', response.data)
        self.assertEqual(response.data['label_id'], 5)
        cls.task = Task.objects.create(status="Running", details={"progress": "50%"})


class TaskTests(SharedDataMixin, TestCase):

    def test_run_pattern_task_with_uri(self):

        async def mock_download_and_extract_tarball(url):
            raise Exception("Download failed")

        task = Task.objects.create(status="Initiated", details={"model": "Pattern", "id": self.pattern.id})

        async def _run_pattern_task():
            await run_pattern_task(self.pattern.id, task.id)

        with patch("core.tasks.download_and_extract_tarball", new=mock_download_and_extract_tarball):
            async_to_sync(_run_pattern_task)()

        task.refresh_from_db()
        self.assertEqual(task.status, "Failed")

    def test_run_pattern_task_without_uri(self):
        pattern = self.pattern
        pattern.collection_version_uri = ""
        pattern.save()

        task = Task.objects.create(status="Initiated", details={"model": "Pattern", "id": pattern.id})

        async def _run_pattern_task():
            await run_pattern_task(pattern.id, task.id)

        async_to_sync(_run_pattern_task)()

        task.refresh_from_db()
        self.assertEqual(task.status, "Completed")
        self.assertIn("Pattern saved without external definition", task.details.get("info", ""))
