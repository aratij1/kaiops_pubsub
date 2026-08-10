from __future__ import annotations

import asyncio
import os
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from ai_workbench_common.agentic import AgentContext, BaseAgent
from common.models import Approval, RemediationAction, RemediationStatus, utc_now
from common.resilience import CircuitBreaker, circuit_breaker
from common.tool_registry import ToolRegistry, ToolSpec


class RemediationPlugin(Protocol):
    action_type: str

    async def execute(self, action: RemediationAction) -> RemediationAction: ...


@dataclass
class BasePlugin:
    action_type: str
    breaker: CircuitBreaker = field(default_factory=CircuitBreaker)

    async def _not_configured(self, action: RemediationAction, executor_name: str) -> RemediationAction:
        await asyncio.sleep(0)
        target = str(action.target or "unknown-target").strip() or "unknown-target"
        service = str(action.parameters.get("service") or "").strip()
        environment = str(action.parameters.get("environment") or "").strip()
        execution_plan = action.parameters.get("execution_plan") if isinstance(action.parameters.get("execution_plan"), dict) else {}
        commands = execution_plan.get("commands") if isinstance(execution_plan.get("commands"), list) else []
        scripts = execution_plan.get("scripts") if isinstance(execution_plan.get("scripts"), list) else []
        queries = execution_plan.get("queries") if isinstance(execution_plan.get("queries"), list) else []

        action.status = RemediationStatus.SKIPPED
        action.error = f"No real {executor_name} executor is configured for action_type={action.action_type}"
        action.output = (
            f"Execution not performed; target={target}; service={service or '-'}; environment={environment or '-'}; "
            f"commands={len(commands)}; scripts={len(scripts)}; queries={len(queries)}. "
            "Configure a connector executor and secret_ref before enabling live remediation."
        )
        action.parameters["execution_result"] = {
            "executed": False,
            "executor": executor_name,
            "reason": action.error,
            "target": target,
            "service": service,
            "environment": environment,
            "commands": commands,
            "scripts": scripts,
            "queries": queries,
        }
        return action


class JenkinsRollbackPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__("rollback_deployment")

    @circuit_breaker(CircuitBreaker())
    async def execute(self, action: RemediationAction) -> RemediationAction:
        return await self._not_configured(action, "jenkins")


class KubernetesRestartPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__("restart_pod")

    @circuit_breaker(CircuitBreaker())
    async def execute(self, action: RemediationAction) -> RemediationAction:
        return await self._not_configured(action, "kubernetes")


class AnsibleRemediationPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__("restart_service")

    async def execute(self, action: RemediationAction) -> RemediationAction:
        return await self._not_configured(action, "ansible")


class TerraformRollbackPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__("terraform_rollback")

    async def execute(self, action: RemediationAction) -> RemediationAction:
        return await self._not_configured(action, "terraform")


class ApiExecutionPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__("api_execution")

    async def execute(self, action: RemediationAction) -> RemediationAction:
        return await self._not_configured(action, "api")


class LocalScriptExecutionPlugin(BasePlugin):
    def __init__(self) -> None:
        super().__init__("script_execution")

    @staticmethod
    def _repo_root() -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / "scripts" / "remediation").is_dir():
                return parent
        return Path("/app")

    def _resolve_script_command(self, action: RemediationAction) -> list[str]:
        execution_plan = action.parameters.get("execution_plan") if isinstance(action.parameters.get("execution_plan"), dict) else {}
        scripts = execution_plan.get("scripts") if isinstance(execution_plan.get("scripts"), list) else []
        commands = action.parameters.get("commands") if isinstance(action.parameters.get("commands"), list) else []
        raw = next(
            (
                str(item).replace("script:", "", 1).strip()
                for item in [*scripts, *commands]
                if "kaiops_alert_health_triage.sh" in str(item)
            ),
            "",
        )
        if not raw:
            raise ValueError("script_execution requires kaiops_alert_health_triage.sh in execution_plan.scripts")

        parts = shlex.split(raw)
        script_index = next((index for index, part in enumerate(parts) if part.endswith("kaiops_alert_health_triage.sh")), -1)
        if script_index < 0:
            raise ValueError("approved script path was not found")

        script_token = parts[script_index]
        relative_script = Path(script_token)
        script_path = relative_script if relative_script.is_absolute() else self._repo_root() / relative_script
        allowed_dir = (self._repo_root() / "scripts" / "remediation").resolve()
        resolved_script = script_path.resolve()
        if allowed_dir not in resolved_script.parents:
            raise PermissionError(f"script path {resolved_script} is outside approved remediation directory")
        if not resolved_script.exists():
            raise FileNotFoundError(f"approved remediation script not found: {resolved_script}")

        arguments = parts[script_index + 1:]
        url_defaults = {
            "--api-gateway-url": os.environ.get("API_GATEWAY_URL", "http://api-gateway:8000"),
            "--prometheus-url": os.environ.get("PROMETHEUS_URL", "http://prometheus:9090"),
        }
        for option, default in url_defaults.items():
            if option not in arguments:
                continue
            value_index = arguments.index(option) + 1
            value = arguments[value_index] if value_index < len(arguments) else ""
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                arguments[value_index:value_index + 1] = [default]

        return ["sh", str(resolved_script), *arguments]

    async def execute(self, action: RemediationAction) -> RemediationAction:
        command = self._resolve_script_command(action)
        script_path = Path(command[1])
        script_input = script_path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        runtime_command = ["sh", "-s", "--", *command[2:]]
        env = os.environ.copy()
        env.setdefault("MYSQL_PASSWORD", env.get("DB_PASSWORD", ""))
        timeout_seconds = float(action.parameters.get("timeout_seconds") or 45)
        process = await asyncio.create_subprocess_exec(
            *runtime_command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=str(self._repo_root()),
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(input=script_input), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            action.status = RemediationStatus.FAILED
            action.error = f"script timed out after {timeout_seconds:g}s"
            action.output = ""
            return action

        output = stdout.decode("utf-8", errors="replace").strip()
        error = stderr.decode("utf-8", errors="replace").strip()
        validation_only = any(
            marker in output.lower()
            for marker in (
                "dry run complete. no remediation mutation was executed",
                "live remediation is intentionally connector-gated",
            )
        )
        action.output = output
        action.error = error if process.returncode else ""
        if process.returncode != 0:
            action.status = RemediationStatus.FAILED
        elif validation_only:
            action.status = RemediationStatus.SKIPPED
            action.error = "Validation completed, but this script did not apply a remediation change. Select a governed live executor to execute the plan."
        else:
            action.status = RemediationStatus.SUCCEEDED
        action.parameters["execution_result"] = {
            "executed": process.returncode == 0 and not validation_only,
            "validation_only": validation_only,
            "executor": "local-script",
            "command": command,
            "runtime_command": runtime_command,
            "returncode": process.returncode,
            "stdout": output,
            "stderr": error,
            "summary": action.error or "Remediation command completed and returned a successful exit status.",
        }
        return action


@dataclass
class RemediationEngine(BaseAgent):
    plugins: dict[str, RemediationPlugin] = field(
        default_factory=lambda: {
            "rollback_deployment": JenkinsRollbackPlugin(),
            "restart_pod": KubernetesRestartPlugin(),
            "scale_deployment": KubernetesRestartPlugin(),
            "restart_service": AnsibleRemediationPlugin(),
            "clear_cache": ApiExecutionPlugin(),
            "failover_database": ApiExecutionPlugin(),
            "api_execution": ApiExecutionPlugin(),
            "script_execution": LocalScriptExecutionPlugin(),
            "terraform_rollback": TerraformRollbackPlugin(),
        }
    )
    tool_registry: ToolRegistry = field(default_factory=ToolRegistry)
    name: str = "automation-agent"

    def __post_init__(self) -> None:
        if self.tool_registry.tools:
            return

        async def _build_tool_handler(plugin: RemediationPlugin, payload: dict[str, Any]) -> dict[str, Any]:
            action_payload = payload.get("action")
            if not isinstance(action_payload, dict):
                raise ValueError("tool payload must include 'action'")
            action = RemediationAction.model_validate(action_payload)
            completed = await plugin.execute(action)
            return completed.model_dump(mode="json")

        for action_type, plugin in self.plugins.items():
            async def handler(payload: dict[str, Any], _plugin: RemediationPlugin = plugin) -> dict[str, Any]:
                return await _build_tool_handler(_plugin, payload)

            self.tool_registry.register(
                ToolSpec(
                    name=action_type,
                    handler=handler,
                    timeout_seconds=12.0,
                    permissions={"automation-agent"},
                )
            )

    async def can_execute(self, context: AgentContext) -> bool:
        return "approval" in context.previous_agent_results

    def is_action_allowed(self, action_type: str) -> bool:
        normalized = str(action_type or "").strip().lower()
        if not normalized:
            return False
        return normalized in set(self.plugins.keys())

    @staticmethod
    def _looks_like_uuid(token: str) -> bool:
        return bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}", token.strip()))

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return str(value or "").strip().lower()

    def _sanitize_recommended_commands(self, commands: list[str]) -> list[str]:
        sanitized: list[str] = []
        seen: set[str] = set()
        for raw in commands:
            token = str(raw or "").strip().strip("`")
            if not token:
                continue
            token = re.sub(r"^\s*(cmd|command|script|query)\s*:\s*", "", token, flags=re.IGNORECASE).strip()
            if not token or token.startswith("#"):
                continue
            lower = token.lower()
            if lower.startswith("preview only") or lower.startswith("recommended_action"):
                continue
            if lower in seen:
                continue
            seen.add(lower)
            sanitized.append(token)
        return sanitized

    def _infer_target_from_commands(self, commands: list[str]) -> str:
        for command in commands:
            token = str(command or "").strip()
            if not token:
                continue

            deployment_match = re.search(r"deployment/([a-z0-9][a-z0-9_.-]*)", token, flags=re.IGNORECASE)
            if deployment_match:
                return deployment_match.group(1)

            service_flag_match = re.search(r"-Service\s+([a-z0-9][a-z0-9_.-]*)", token, flags=re.IGNORECASE)
            if service_flag_match:
                return service_flag_match.group(1)

            service_arg_match = re.search(r"service=([a-z0-9][a-z0-9_.-]*)", token, flags=re.IGNORECASE)
            if service_arg_match:
                return service_arg_match.group(1)

            findstr_match = re.search(r"findstr\s+([a-z0-9][a-z0-9_.-]*)", token, flags=re.IGNORECASE)
            if findstr_match:
                return findstr_match.group(1)

        return ""

    def _infer_action_type(self, *, action_text: str, commands: list[str]) -> str:
        text = self._normalize_text(action_text)
        command_blob = " | ".join(self._normalize_text(item) for item in commands)
        haystack = f"{text} | {command_blob}"

        if "kaiops_alert_health_triage.sh" in haystack:
            return "script_execution"
        if any(keyword in haystack for keyword in ["restart pod", "rollout restart", "crashloop", "oom"]):
            return "restart_pod"
        if any(keyword in haystack for keyword in ["scale", "replicas", "hpa"]):
            return "scale_deployment"
        if any(keyword in haystack for keyword in ["restart service", "systemctl restart", "ansible"]):
            return "restart_service"
        if any(keyword in haystack for keyword in ["cache", "redis", "flushdb"]):
            return "clear_cache"
        if any(keyword in haystack for keyword in ["failover", "database", "replica", "mysql"]):
            return "failover_database"
        if any(keyword in haystack for keyword in ["terraform", "infrastructure rollback"]):
            return "terraform_rollback"
        return "rollback_deployment"

    def build_action(self, approval: Approval) -> RemediationAction:
        recommended_action = str(approval.metadata.get("recommended_action") or "").strip()
        recommended_commands = approval.metadata.get("recommended_commands") if isinstance(approval.metadata.get("recommended_commands"), list) else []
        approved_execution_plan = approval.metadata.get("execution_plan") if isinstance(approval.metadata.get("execution_plan"), dict) else {}
        action_text = str(approval.modified_action or approval.comment or recommended_action or "rollback deployment").strip()
        plan_commands = approved_execution_plan.get("commands") if isinstance(approved_execution_plan.get("commands"), list) else []
        plan_scripts = approved_execution_plan.get("scripts") if isinstance(approved_execution_plan.get("scripts"), list) else []
        plan_queries = approved_execution_plan.get("queries") if isinstance(approved_execution_plan.get("queries"), list) else []
        has_approved_execution_plan = isinstance(approval.metadata.get("execution_plan"), dict)
        command_list = self._sanitize_recommended_commands([
            *[str(item) for item in recommended_commands],
            *[str(item) for item in plan_commands],
            *[f"script: {item}" for item in plan_scripts],
            *[f"query: {item}" for item in plan_queries],
        ])
        inferred_target = self._infer_target_from_commands(command_list)
        action_type = self._infer_action_type(action_text=action_text, commands=command_list)
        policy_version = str(approval.metadata.get("policy_version", "")).strip()
        policy_reason = str(approval.metadata.get("policy_reason", "")).strip()

        target_candidates = [
            approval.metadata.get("remediation_target"),
            approval.metadata.get("target"),
            approval.metadata.get("deployment"),
            approval.metadata.get("resource"),
            approval.metadata.get("service"),
            approval.metadata.get("incident_service"),
            inferred_target,
            approval.metadata.get("incident_id"),
            approval.incident_id,
        ]
        target = str(next((value for value in target_candidates if value), approval.incident_id)).strip()
        service = str(approval.metadata.get("service") or approval.metadata.get("incident_service") or inferred_target or "").strip()
        environment = str(approval.metadata.get("environment") or "").strip()
        if self._looks_like_uuid(target) and service:
            target = service
        generated_execution_plan = self._build_execution_plan(
            action_type=action_type,
            target=target,
            service=service,
            environment=environment,
            recommended_action=recommended_action,
            recommended_commands=command_list,
        )
        execution_plan = {
            "commands": [
                str(item).strip()
                for item in (plan_commands if has_approved_execution_plan else generated_execution_plan.get("commands", []))
                if str(item).strip()
            ],
            "scripts": [
                str(item).strip()
                for item in (plan_scripts if has_approved_execution_plan else generated_execution_plan.get("scripts", []))
                if str(item).strip()
            ],
            "queries": [
                str(item).strip()
                for item in (plan_queries if has_approved_execution_plan else generated_execution_plan.get("queries", []))
                if str(item).strip()
            ],
        }
        connection_profile = approval.metadata.get("connection_profile") if isinstance(approval.metadata.get("connection_profile"), dict) else {}

        return RemediationAction(
            incident_id=approval.incident_id,
            approval_id=approval.id,
            action_type=action_type,
            target=target,
            parameters={
                "approved_by": approval.approver,
                "channel": approval.channel,
                "policy_version": policy_version,
                "policy_reason": policy_reason,
                "service": service,
                "environment": environment,
                "recommended_action": recommended_action,
                "commands": command_list,
                "execution_plan": execution_plan,
                "connection_profile": connection_profile,
                "runbook_id": str(approval.metadata.get("runbook_id") or ""),
                "runbook_version": approval.metadata.get("runbook_version"),
                "runbook_status": str(approval.metadata.get("runbook_status") or ""),
                "runbook_match_score": approval.metadata.get("runbook_match_score"),
                "operator_modified": bool(approval.modified_action),
            },
            started_at=utc_now(),
            status=RemediationStatus.RUNNING,
        )

    def _build_execution_plan(
        self,
        *,
        action_type: str,
        target: str,
        service: str,
        environment: str,
        recommended_action: str,
        recommended_commands: list[str],
    ) -> dict[str, list[str]]:
        namespace = environment or "prod"
        resolved_target = target or service or "unknown-target"

        if action_type == "restart_pod":
            commands = [
                f"kubectl rollout restart deployment/{resolved_target} -n {namespace}",
                f"kubectl rollout status deployment/{resolved_target} -n {namespace} --timeout=180s",
            ]
            scripts = [
                f"scripts/remediation/restart_pod.ps1 -Service {resolved_target} -Namespace {namespace}",
            ]
            queries = [
                f"sum(rate(http_requests_total{{service='{resolved_target}',status=~'5..'}}[5m]))",
            ]
        elif action_type == "scale_deployment":
            commands = [
                f"kubectl scale deployment/{resolved_target} --replicas=3 -n {namespace}",
                f"kubectl rollout status deployment/{resolved_target} -n {namespace} --timeout=180s",
            ]
            scripts = [
                f"scripts/remediation/scale_deployment.ps1 -Service {resolved_target} -Namespace {namespace} -Replicas 3",
            ]
            queries = [
                f"avg_over_time(container_cpu_usage_seconds_total{{pod=~'{resolved_target}.*'}}[10m])",
            ]
        elif action_type == "restart_service":
            commands = [
                f"ansible-playbook playbooks/restart-service.yml -e service={resolved_target} -e env={namespace}",
            ]
            scripts = [
                f"scripts/remediation/restart_service.ps1 -Service {resolved_target} -Environment {namespace}",
            ]
            queries = [
                f"max_over_time(up{{job='{resolved_target}'}}[5m])",
            ]
        elif action_type == "clear_cache":
            commands = [
                f"redis-cli -h {resolved_target}-redis -n 0 FLUSHDB",
            ]
            scripts = [
                f"scripts/remediation/clear_cache.ps1 -Service {resolved_target}",
            ]
            queries = [
                f"sum(rate(cache_miss_total{{service='{resolved_target}'}}[5m]))",
            ]
        elif action_type == "failover_database":
            commands = [
                "mysql -e \"CALL mysql.rds_failover();\"",
            ]
            scripts = [
                "scripts/remediation/failover_database.ps1",
            ]
            queries = [
                "SHOW REPLICA STATUS;",
                f"sum(rate(mysql_global_status_queries{{service='{resolved_target}'}}[5m]))",
            ]
        elif action_type == "terraform_rollback":
            commands = [
                "terraform init",
                f"terraform apply -auto-approve -var service={resolved_target} -var rollback=true",
            ]
            scripts = [
                f"scripts/remediation/terraform_rollback.ps1 -Service {resolved_target} -Environment {namespace}",
            ]
            queries = [
                f"sum(rate(terraform_apply_failures_total{{service='{resolved_target}'}}[15m]))",
            ]
        else:
            commands = [
                f"kubectl rollout undo deployment/{resolved_target} -n {namespace}",
                f"kubectl rollout status deployment/{resolved_target} -n {namespace} --timeout=180s",
            ]
            scripts = [
                f"scripts/remediation/rollback_deployment.ps1 -Service {resolved_target} -Namespace {namespace}",
            ]
            queries = [
                f"sum(rate(http_requests_total{{service='{resolved_target}',status=~'5..'}}[5m]))",
            ]

        if recommended_commands:
            deduped = []
            seen = set()
            for item in [*recommended_commands, *commands]:
                key = str(item or "").strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                deduped.append(str(item).strip())
            commands = deduped
            if any("kaiops_alert_health_triage.sh" in str(item) for item in recommended_commands):
                scripts = [
                    str(item).replace("script:", "", 1).strip()
                    for item in recommended_commands
                    if "kaiops_alert_health_triage.sh" in str(item)
                ] or scripts

        return {
            "commands": commands,
            "scripts": scripts,
            "queries": queries,
        }

    async def execute(self, action: RemediationAction) -> RemediationAction:
        action_type = action.action_type if action.action_type in self.tool_registry.tools else "api_execution"
        try:
            payload = await self.tool_registry.execute(
                action_type,
                {"action": action.model_dump(mode="json")},
                role="automation-agent",
            )
            completed = RemediationAction.model_validate(payload)
            completed.completed_at = utc_now()
            return completed
        except Exception as exc:
            action.status = RemediationStatus.FAILED
            action.error = str(exc)
            action.completed_at = utc_now()
            return action

    async def execute_from_context(self, context: AgentContext) -> RemediationAction:
        approval_payload = context.previous_agent_results.get("approval")
        if not isinstance(approval_payload, dict):
            raise ValueError("AgentContext.previous_agent_results['approval'] is required")
        action = self.build_action(Approval.model_validate(approval_payload))
        result = await self.execute(action)
        context.set_result("remediation-action", result.model_dump(mode="json"))
        return result

    async def validate(self, result: Any) -> bool:
        return isinstance(result, RemediationAction)
