from scripts.generate_jenkins_application_jobs import generate


def test_generates_scoped_job_for_each_application() -> None:
    catalog = {
        "version": 1,
        "defaults": ["investigate-first"],
        "technology_profiles": {"python-fastapi": ["restart-workload"]},
        "resolutions": {"investigate-first": {"risk": "low"}, "restart-workload": {"risk": "medium"}},
    }
    result = generate([
        {"name": "Payments API", "technology": "python-fastapi", "environment": "prod", "namespace": "payments"},
        {"name": "Legacy ERP", "technology": "unknown", "environment": "prod", "namespace": "erp"},
    ], catalog)

    assert [job["job_name"] for job in result["jobs"]] == ["kaiops/remediation/payments-api", "kaiops/remediation/legacy-erp"]
    assert result["jobs"][0]["resolution_ids"] == ["restart-workload", "investigate-first"]
    assert result["jobs"][1]["resolution_ids"] == ["investigate-first"]
