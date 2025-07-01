from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from core.models import Task
from core.tasks import run_pattern_instance_task


class SharedDataMixin:
    @classmethod
    def setUpTestData(cls):
        cls.task1 = Task.objects.create(status="Running", details={"progress": "50%"})
        cls.task2 = Task.objects.create(status="Completed", details={"result": "success"})
        cls.task3 = Task.objects.create(status="Failed", details={"error": "timeout"})


class TaskViewSetTest(SharedDataMixin, APITestCase):
    def test_task_list_view(self):
        url = reverse("task-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 3)

    def test_pattern_detail_view(self):
        url = reverse("pattern-detail", args=[self.pattern.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["collection_name"], "mynamespace.mycollection")

    def test_pattern_create_view(self):
        url = reverse("pattern-list")
        data = {
            "collection_name": "new.namespace.collection",
            "collection_version": "1.2.3",
            "collection_version_uri": "https://example.com/new.tar.gz",
            "pattern_name": "new_pattern",
        }

        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

        # Pattern created
        pattern = Pattern.objects.get(pattern_name="new_pattern")
        self.assertIsNotNone(pattern)

        # Task id returned directly
        task_id = response.data.get("task_id")
        self.assertIsInstance(task_id, int)

        # Task exists
        task = Task.objects.get(id=task_id)
        self.assertEqual(task.status, "Initiated")
        self.assertEqual(task.details.get("model"), "Pattern")
        self.assertEqual(task.details.get("id"), pattern.id)


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
        self.assertIn('status', response.data)
        self.assertIn('details', response.data)

    def test_task_list_view_returns_all_tasks(self):
        url = reverse("task-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Verify we get all created tasks
        task_ids = [task['id'] for task in response.data]
        expected_ids = [self.task1.id, self.task2.id, self.task3.id]
        self.assertEqual(sorted(task_ids), sorted(expected_ids))

    def test_task_detail_view_for_different_statuses(self):
        tasks_to_test = [(self.task1, "Running"), (self.task2, "Completed"), (self.task3, "Failed")]

        for task, expected_status in tasks_to_test:
            with self.subTest(status=expected_status):
                url = reverse("task-detail", args=[task.pk])
                response = self.client.get(url)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_task_detail_view_nonexistent_task(self):
        url = reverse("task-detail", args=[99999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
