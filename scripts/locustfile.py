"""Short load against the local locate server. Not part of the held-out score."""

from __future__ import annotations

import random

from locust import HttpUser, between, task

REPORTS = [
    "QuerySet.filter returns the wrong rows when the lookup value is None",
    "ModelForm does not save a nullable foreign key on PostgreSQL",
    "altering a field crashes in the schema editor",
    "prefetch_related drops rows when the cache is stale",
]


class LocateUser(HttpUser):
    wait_time = between(0.05, 0.15)

    @task
    def locate(self):
        self.client.post(
            "/locate",
            json={"report": random.choice(REPORTS), "k": 5},
            name="/locate",
        )
