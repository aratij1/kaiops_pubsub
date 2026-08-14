# KaiOps Jenkins application remediation

KaiOps uses one governed Jenkins job per registered application. Every job uses
`Jenkinsfile.auto-remediation`; application-specific resolution choices come
from `application-resolution-catalog.json`.

Generate the job inventory from a running KaiOps application registry:

```bash
python scripts/generate_jenkins_application_jobs.py \
  --applications http://application-onboarding:8000/applications \
  --output deploy/jenkins/generated/application-jobs.json
```

Create a Jenkins Pipeline job for each `jobs[]` entry using its `job_name` and
`jenkinsfile`. Configure the remediation-engine connection profile with the
same job name, Jenkins endpoint, secret-manager credential reference, and
allowed operation IDs.

The resolution agent supplies the selected catalog resolution and execution
plan. Jenkins then:

1. validates the incident, target, resolution, command allowlist, and approval;
2. runs in dry-run mode by default;
3. executes only the approved commands when dry-run is disabled;
4. archives application, validation, and rollback evidence for closure.

Jenkins credentials must be injected into remediation-engine as
`JENKINS_USERNAME` and `JENKINS_API_TOKEN`. Store only the credential reference
in application or connector configuration.
