from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.cloud_operations.models import (
    CloudConnection,
    CloudConnectionCreate,
    ConnectionStatus,
    ConnectionValidationResult,
    DiscoveredResource,
    DiscoveryRequest,
    DiscoveryResult,
    DiscoveryStatus,
    ResourceRelationship,
    ServiceOnboardingProfile,
    ServiceOnboardingState,
)
from common.database import (
    CloudAuditEventRecord,
    ConnectionHealthCheckRecord,
    DiscoveredResourceRecord,
    DiscoveryRunRecord,
    ProviderConnectionRecord,
    ResourceRelationshipRecord,
    ServiceOnboardingProfileRecord,
    ServiceReadinessScoreRecord,
    ServiceResourceMappingRecord,
)
from common.models import utc_now


def _connection_from_record(row: ProviderConnectionRecord) -> CloudConnection:
    return CloudConnection(
        id=row.id,
        tenant_id=row.tenant_id,
        project_id=row.project_id,
        provider_type=row.provider_type,
        connection_name=row.connection_name,
        credential_ref=row.credential_ref,
        auth_method=row.auth_method,
        allowed_regions=list(row.allowed_regions or []),
        resource_filters=dict(row.resource_filters or {}),
        discovery_scope=dict(row.discovery_scope or {}),
        read_capability=bool(row.read_capability),
        write_capability=bool(row.write_capability),
        connection_owner=row.connection_owner,
        status=row.status,
        failure_reason=row.failure_reason,
        last_health_check_at=row.last_health_check_at,
        last_discovery_at=row.last_discovery_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        version=int(row.version or 1),
    )


class CloudOperationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_connection(self, payload: CloudConnectionCreate) -> ProviderConnectionRecord:
        row = ProviderConnectionRecord(
            tenant_id=payload.tenant_id,
            project_id=payload.project_id,
            provider_type=payload.provider_type.value,
            connection_name=payload.connection_name,
            credential_ref=payload.credential_ref,
            auth_method=payload.auth_method,
            allowed_regions=payload.allowed_regions,
            resource_filters=payload.resource_filters,
            discovery_scope=payload.discovery_scope,
            read_capability=payload.read_capability,
            write_capability=payload.write_capability,
            connection_owner=payload.connection_owner,
            status=ConnectionStatus.DRAFT.value,
        )
        self.session.add(row)
        await self.audit(
            tenant_id=payload.tenant_id,
            project_id=payload.project_id,
            actor=payload.connection_owner,
            action="connection.created",
            resource_type="provider_connection",
            resource_id=str(row.id),
            payload={"provider_type": payload.provider_type.value, "write_capability": payload.write_capability},
        )
        await self.session.flush()
        return row

    async def list_connections(self, *, tenant_id: str, project_id: str | None = None) -> list[ProviderConnectionRecord]:
        stmt = select(ProviderConnectionRecord).where(ProviderConnectionRecord.tenant_id == tenant_id)
        if project_id:
            stmt = stmt.where(ProviderConnectionRecord.project_id == project_id)
        result = await self.session.execute(stmt.order_by(ProviderConnectionRecord.updated_at.desc()))
        return list(result.scalars().all())

    async def get_connection(self, connection_id: UUID, *, tenant_id: str) -> ProviderConnectionRecord | None:
        return (
            await self.session.execute(
                select(ProviderConnectionRecord).where(
                    ProviderConnectionRecord.id == connection_id,
                    ProviderConnectionRecord.tenant_id == tenant_id,
                )
            )
        ).scalar_one_or_none()

    async def record_validation(
        self,
        row: ProviderConnectionRecord,
        result: ConnectionValidationResult,
        *,
        actor: str = "system",
    ) -> ConnectionHealthCheckRecord:
        row.status = ConnectionStatus.VALIDATED.value if result.status == "validated" else ConnectionStatus.FAILED.value
        row.failure_reason = None if result.status == "validated" else result.message
        row.last_health_check_at = result.checked_at
        row.version = int(row.version or 1) + 1
        health = ConnectionHealthCheckRecord(
            connection_id=row.id,
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            provider_type=row.provider_type,
            status=result.status,
            connectivity_ok=result.connectivity_ok,
            authentication_ok=result.authentication_ok,
            requested_permissions=result.requested_permissions,
            granted_permissions=result.granted_permissions,
            missing_permissions=result.missing_permissions,
            payload=result.model_dump(mode="json"),
        )
        self.session.add(health)
        await self.audit(
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            actor=actor,
            action=f"connection.{result.status}",
            resource_type="provider_connection",
            resource_id=str(row.id),
            payload=result.model_dump(mode="json"),
        )
        await self.session.flush()
        return health

    async def start_discovery(self, row: ProviderConnectionRecord, request: DiscoveryRequest) -> DiscoveryRunRecord:
        run = DiscoveryRunRecord(
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            connection_id=row.id,
            provider_type=row.provider_type,
            status=DiscoveryStatus.STARTED.value,
            requested_by=request.actor,
            discovery_scope=request.model_dump(mode="json"),
            started_at=utc_now(),
        )
        self.session.add(run)
        await self.session.flush()
        return run

    async def complete_discovery(
        self,
        row: ProviderConnectionRecord,
        run: DiscoveryRunRecord,
        result: DiscoveryResult,
        *,
        request: DiscoveryRequest,
    ) -> None:
        now = utc_now()
        run.status = result.status.value if hasattr(result.status, "value") else str(result.status)
        run.resource_count = len(result.resources)
        run.relationship_count = len(result.relationships)
        run.completed_at = now
        run.payload = {"message": result.message}
        row.last_discovery_at = now
        row.version = int(row.version or 1) + 1
        for resource in result.resources:
            await self.upsert_resource(resource)
        for relationship in result.relationships:
            await self.upsert_relationship(relationship)
        await self.audit(
            tenant_id=row.tenant_id,
            project_id=row.project_id,
            actor=request.actor,
            action="discovery.completed",
            resource_type="discovery_run",
            resource_id=str(run.id),
            payload={"resource_count": len(result.resources), "relationship_count": len(result.relationships)},
        )
        await self.session.flush()

    async def upsert_resource(self, resource: DiscoveredResource) -> DiscoveredResourceRecord:
        existing = (
            await self.session.execute(
                select(DiscoveredResourceRecord).where(
                    DiscoveredResourceRecord.tenant_id == resource.tenant_id,
                    DiscoveredResourceRecord.project_id == resource.project_id,
                    DiscoveredResourceRecord.provider_resource_id == resource.provider_resource_id,
                )
            )
        ).scalar_one_or_none()
        values = resource.model_dump(mode="json")
        if existing is None:
            existing = DiscoveredResourceRecord(
                id=resource.id,
                tenant_id=resource.tenant_id,
                project_id=resource.project_id,
                service_id=resource.service_id,
                environment=resource.environment,
                provider=resource.provider.value,
                provider_account_id=resource.provider_account_id,
                region=resource.region,
                provider_resource_id=resource.provider_resource_id,
                resource_type=resource.resource_type,
                display_name=resource.display_name,
                status=resource.status.value,
                tags=resource.tags,
                owner=resource.owner,
                configuration=resource.configuration,
                health=resource.health,
                cost=resource.cost,
                discovered_at=resource.discovered_at,
            )
            self.session.add(existing)
        else:
            existing.service_id = resource.service_id
            existing.environment = resource.environment
            existing.resource_type = resource.resource_type
            existing.display_name = resource.display_name
            existing.status = resource.status.value
            existing.tags = resource.tags
            existing.owner = resource.owner
            existing.configuration = resource.configuration
            existing.health = resource.health
            existing.cost = resource.cost
            existing.discovered_at = resource.discovered_at
            existing.version = int(existing.version or 1) + 1
        await self.audit(
            tenant_id=resource.tenant_id,
            project_id=resource.project_id,
            actor="discovery",
            action="resource.discovered",
            resource_type=resource.resource_type,
            resource_id=str(existing.id),
            payload=values,
        )
        return existing

    async def upsert_relationship(self, relationship: ResourceRelationship) -> ResourceRelationshipRecord:
        existing = (
            await self.session.execute(
                select(ResourceRelationshipRecord).where(
                    ResourceRelationshipRecord.tenant_id == relationship.tenant_id,
                    ResourceRelationshipRecord.project_id == relationship.project_id,
                    ResourceRelationshipRecord.source_resource_id == relationship.source_resource_id,
                    ResourceRelationshipRecord.target_resource_id == relationship.target_resource_id,
                    ResourceRelationshipRecord.relationship_type == relationship.relationship_type,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = ResourceRelationshipRecord(**relationship.model_dump(mode="python"))
            self.session.add(existing)
        else:
            existing.source = relationship.source
            existing.confidence = relationship.confidence
            existing.owner_confirmed = relationship.owner_confirmed
            existing.discovered_at = relationship.discovered_at
            existing.version = int(existing.version or 1) + 1
        return existing

    async def list_resources(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        service_id: str | None = None,
        environment: str | None = None,
    ) -> list[DiscoveredResourceRecord]:
        stmt = select(DiscoveredResourceRecord).where(DiscoveredResourceRecord.tenant_id == tenant_id)
        if project_id:
            stmt = stmt.where(DiscoveredResourceRecord.project_id == project_id)
        if service_id:
            stmt = stmt.where(DiscoveredResourceRecord.service_id == service_id)
        if environment:
            stmt = stmt.where(DiscoveredResourceRecord.environment == environment)
        result = await self.session.execute(stmt.order_by(DiscoveredResourceRecord.updated_at.desc()).limit(500))
        return list(result.scalars().all())

    async def map_service(
        self,
        *,
        tenant_id: str,
        project_id: str,
        service_id: str,
        environment: str,
        resource_ids: list[str],
        owner: str,
    ) -> list[ServiceResourceMappingRecord]:
        rows: list[ServiceResourceMappingRecord] = []
        for resource_id in resource_ids:
            existing_result = await self.session.execute(
                select(ServiceResourceMappingRecord).where(
                    ServiceResourceMappingRecord.tenant_id == tenant_id,
                    ServiceResourceMappingRecord.project_id == project_id,
                    ServiceResourceMappingRecord.service_id == service_id,
                    ServiceResourceMappingRecord.environment == environment,
                    ServiceResourceMappingRecord.resource_id == resource_id,
                )
            )
            existing = existing_result.scalar_one_or_none()
            if existing:
                existing.status = "active"
                existing.owner = owner
                rows.append(existing)
                continue
            mapping_id = uuid4()
            row = ServiceResourceMappingRecord(
                id=mapping_id,
                tenant_id=tenant_id,
                project_id=project_id,
                service_id=service_id,
                environment=environment,
                resource_id=resource_id,
                owner=owner,
                mapping_source="operator",
                status="active",
            )
            self.session.add(row)
            rows.append(row)
        await self.audit(
            tenant_id=tenant_id,
            project_id=project_id,
            actor=owner,
            action="service.resources.mapped",
            resource_type="service",
            resource_id=service_id,
            payload={"resource_ids": resource_ids, "environment": environment},
        )
        await self.session.flush()
        return rows

    async def upsert_service_onboarding(self, profile: ServiceOnboardingProfile) -> ServiceOnboardingProfileRecord:
        existing = (
            await self.session.execute(
                select(ServiceOnboardingProfileRecord).where(
                    ServiceOnboardingProfileRecord.tenant_id == profile.tenant_id,
                    ServiceOnboardingProfileRecord.project_id == profile.project_id,
                    ServiceOnboardingProfileRecord.service_id == profile.service_id,
                    ServiceOnboardingProfileRecord.environment == profile.environment,
                )
            )
        ).scalar_one_or_none()
        telemetry = {
            "monitoring_sources": profile.monitoring_sources,
            "log_sources": profile.log_sources,
            "metric_sources": profile.metric_sources,
            "trace_sources": profile.trace_sources,
            "event_sources": profile.event_sources,
        }
        if existing is None:
            existing = ServiceOnboardingProfileRecord(
                tenant_id=profile.tenant_id,
                project_id=profile.project_id,
                service_id=profile.service_id,
                environment=profile.environment,
                template_id=profile.template_id,
                business_criticality=profile.business_criticality,
                owners=profile.owners,
                support_groups=profile.support_groups,
                connection_ids=profile.connection_ids,
                telemetry=telemetry,
                slos=profile.slos,
                business_kpis=profile.business_kpis,
                change_sources=profile.change_sources,
                knowledge_refs=profile.knowledge_refs,
                diagnostic_capabilities=profile.diagnostic_capabilities,
                remediation_capabilities=profile.remediation_capabilities,
                validation_rules=profile.validation_rules,
                escalation_policies=profile.escalation_policies,
                hitl_policy=profile.hitl_policy,
                dependencies=profile.dependencies,
                metadata_payload=profile.metadata,
            )
            self.session.add(existing)
        else:
            existing.template_id = profile.template_id
            existing.business_criticality = profile.business_criticality
            existing.owners = profile.owners
            existing.support_groups = profile.support_groups
            existing.connection_ids = profile.connection_ids
            existing.telemetry = telemetry
            existing.slos = profile.slos
            existing.business_kpis = profile.business_kpis
            existing.change_sources = profile.change_sources
            existing.knowledge_refs = profile.knowledge_refs
            existing.diagnostic_capabilities = profile.diagnostic_capabilities
            existing.remediation_capabilities = profile.remediation_capabilities
            existing.validation_rules = profile.validation_rules
            existing.escalation_policies = profile.escalation_policies
            existing.hitl_policy = profile.hitl_policy
            existing.dependencies = profile.dependencies
            existing.metadata_payload = profile.metadata
            existing.version = int(existing.version or 1) + 1
        await self.audit(
            tenant_id=profile.tenant_id,
            project_id=profile.project_id,
            actor=profile.actor,
            action="service.onboarding.updated",
            resource_type="service",
            resource_id=profile.service_id,
            payload=self.onboarding_payload(existing),
        )
        await self.session.flush()
        return existing

    async def get_service_onboarding(
        self,
        *,
        tenant_id: str,
        project_id: str,
        service_id: str,
        environment: str,
    ) -> ServiceOnboardingProfileRecord | None:
        return (
            await self.session.execute(
                select(ServiceOnboardingProfileRecord).where(
                    ServiceOnboardingProfileRecord.tenant_id == tenant_id,
                    ServiceOnboardingProfileRecord.project_id == project_id,
                    ServiceOnboardingProfileRecord.service_id == service_id,
                    ServiceOnboardingProfileRecord.environment == environment,
                )
            )
        ).scalar_one_or_none()

    async def recalculate_readiness(
        self,
        *,
        tenant_id: str,
        project_id: str,
        service_id: str,
        environment: str,
        actor: str = "system",
    ) -> ServiceReadinessScoreRecord:
        profile = await self.get_service_onboarding(
            tenant_id=tenant_id,
            project_id=project_id,
            service_id=service_id,
            environment=environment,
        )
        resources = await self.list_resources(tenant_id=tenant_id, project_id=project_id, service_id=service_id, environment=environment)
        resource_ids = {str(row.id) for row in resources}
        relationships = await self._relationships_for_resources(tenant_id=tenant_id, project_id=project_id, resource_ids=resource_ids)
        telemetry = dict(profile.telemetry or {}) if profile else {}
        scores = {
            "ownership": _score(bool(profile and profile.owners), bool(profile and profile.support_groups)),
            "resource_coverage": _score(bool(resources), len(resources) >= 3),
            "telemetry": _score(
                bool(telemetry.get("monitoring_sources")),
                bool(telemetry.get("metric_sources")),
                bool(telemetry.get("log_sources") or telemetry.get("trace_sources") or telemetry.get("event_sources")),
            ),
            "topology": _score(bool(relationships), len(relationships) >= max(1, len(resources) - 1)),
            "knowledge": _score(bool(profile and profile.knowledge_refs), bool(profile and profile.escalation_policies)),
            "diagnostics": _score(bool(profile and profile.diagnostic_capabilities)),
            "automation": _score(bool(profile and profile.remediation_capabilities), bool(profile and profile.hitl_policy)),
            "validation": _score(bool(profile and profile.validation_rules), bool(profile and profile.slos)),
            "security": _score(bool(profile and profile.connection_ids), bool(profile and profile.hitl_policy)),
        }
        overall = round(sum(scores.values()) / len(scores), 4)
        state = self._readiness_state(overall, scores, bool(resources), bool(telemetry.get("monitoring_sources")))
        existing = (
            await self.session.execute(
                select(ServiceReadinessScoreRecord).where(
                    ServiceReadinessScoreRecord.tenant_id == tenant_id,
                    ServiceReadinessScoreRecord.project_id == project_id,
                    ServiceReadinessScoreRecord.service_id == service_id,
                    ServiceReadinessScoreRecord.environment == environment,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            existing = ServiceReadinessScoreRecord(
                tenant_id=tenant_id,
                project_id=project_id,
                service_id=service_id,
                environment=environment,
                readiness_state=state.value,
                overall_score=overall,
                scores=scores,
            )
            self.session.add(existing)
        else:
            existing.readiness_state = state.value
            existing.overall_score = overall
            existing.scores = scores
            existing.version = int(existing.version or 1) + 1
        if profile:
            profile.onboarding_state = state.value
        await self.audit(
            tenant_id=tenant_id,
            project_id=project_id,
            actor=actor,
            action="service.readiness.changed",
            resource_type="service",
            resource_id=service_id,
            payload={"environment": environment, "readiness_state": state.value, "overall_score": overall, "scores": scores},
        )
        await self.session.flush()
        return existing

    async def service_360(self, *, tenant_id: str, project_id: str, service_id: str, environment: str | None = None) -> dict[str, Any]:
        resources = await self.list_resources(
            tenant_id=tenant_id,
            project_id=project_id,
            service_id=service_id,
            environment=environment,
        )
        resource_ids = {str(row.id) for row in resources}
        relationships = await self._relationships_for_resources(tenant_id=tenant_id, project_id=project_id, resource_ids=resource_ids)
        health_counts: dict[str, int] = {}
        for row in resources:
            status = str((row.health or {}).get("status") or row.status or "unknown")
            health_counts[status] = health_counts.get(status, 0) + 1
        score = (
            await self.session.execute(
                select(ServiceReadinessScoreRecord).where(
                    ServiceReadinessScoreRecord.tenant_id == tenant_id,
                    ServiceReadinessScoreRecord.project_id == project_id,
                    ServiceReadinessScoreRecord.service_id == service_id,
                )
            )
        ).scalar_one_or_none()
        return {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "service_id": service_id,
            "environment": environment,
            "health": health_counts,
            "resources": [self.resource_payload(row) for row in resources],
            "relationships": [self.relationship_payload(row) for row in relationships],
            "readiness": dict(score.scores or {}) if score else {},
            "overall_score": float(score.overall_score or 0.0) if score else 0.0,
            "readiness_state": score.readiness_state if score else "DRAFT",
        }

    async def topology(self, *, tenant_id: str, project_id: str, service_id: str, environment: str | None = None) -> dict[str, Any]:
        resources = await self.list_resources(tenant_id=tenant_id, project_id=project_id, service_id=service_id, environment=environment)
        resource_ids = {str(row.id) for row in resources}
        relationships = await self._relationships_for_resources(tenant_id=tenant_id, project_id=project_id, resource_ids=resource_ids)
        return {
            "nodes": [self.resource_payload(row) for row in resources],
            "edges": [self.relationship_payload(row) for row in relationships],
        }

    async def cockpit(self, *, tenant_id: str, project_id: str | None = None, environment: str | None = None) -> dict[str, Any]:
        resources = await self.list_resources(tenant_id=tenant_id, project_id=project_id, environment=environment)
        readiness_stmt = select(ServiceReadinessScoreRecord).where(ServiceReadinessScoreRecord.tenant_id == tenant_id)
        if project_id:
            readiness_stmt = readiness_stmt.where(ServiceReadinessScoreRecord.project_id == project_id)
        if environment:
            readiness_stmt = readiness_stmt.where(ServiceReadinessScoreRecord.environment == environment)
        readiness_rows = list((await self.session.execute(readiness_stmt)).scalars().all())
        health: dict[str, int] = {}
        by_provider: dict[str, int] = {}
        by_environment: dict[str, int] = {}
        for row in resources:
            health_key = str((row.health or {}).get("status") or row.status or "unknown")
            health[health_key] = health.get(health_key, 0) + 1
            by_provider[row.provider] = by_provider.get(row.provider, 0) + 1
            by_environment[row.environment] = by_environment.get(row.environment, 0) + 1
        return {
            "resource_count": len(resources),
            "service_count": len({(row.project_id, row.service_id, row.environment) for row in resources}),
            "health": health,
            "by_provider": by_provider,
            "by_environment": by_environment,
            "readiness": [
                {
                    "project_id": row.project_id,
                    "service_id": row.service_id,
                    "environment": row.environment,
                    "readiness_state": row.readiness_state,
                    "overall_score": float(row.overall_score or 0.0),
                    "scores": row.scores or {},
                }
                for row in readiness_rows
            ],
        }

    async def _relationships_for_resources(
        self,
        *,
        tenant_id: str,
        project_id: str,
        resource_ids: set[str],
    ) -> list[ResourceRelationshipRecord]:
        if not resource_ids:
            return []
        relationship_stmt = select(ResourceRelationshipRecord).where(
            ResourceRelationshipRecord.tenant_id == tenant_id,
            ResourceRelationshipRecord.project_id == project_id,
        )
        return [
            row
            for row in (await self.session.execute(relationship_stmt)).scalars().all()
            if row.source_resource_id in resource_ids or row.target_resource_id in resource_ids
        ]

    @staticmethod
    def _readiness_state(
        overall: float,
        scores: dict[str, float],
        has_resources: bool,
        has_monitoring: bool,
    ) -> ServiceOnboardingState:
        if overall >= 0.82 and scores["automation"] >= 0.5 and scores["validation"] >= 0.5:
            return ServiceOnboardingState.OPERABLE
        if overall >= 0.68 and scores["knowledge"] >= 0.5 and scores["security"] >= 0.5:
            return ServiceOnboardingState.INCIDENT_READY
        if has_resources and has_monitoring and overall >= 0.45:
            return ServiceOnboardingState.OBSERVABLE
        if has_resources:
            return ServiceOnboardingState.DISCOVERED
        return ServiceOnboardingState.DRAFT

    async def audit(
        self,
        *,
        tenant_id: str,
        project_id: str,
        actor: str,
        action: str,
        resource_type: str,
        resource_id: str,
        payload: dict[str, Any],
    ) -> None:
        self.session.add(
            CloudAuditEventRecord(
                tenant_id=tenant_id,
                project_id=project_id,
                actor=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                payload=payload,
            )
        )

    @staticmethod
    def connection_payload(row: ProviderConnectionRecord) -> dict[str, Any]:
        return _connection_from_record(row).model_dump(mode="json")

    @staticmethod
    def resource_payload(row: DiscoveredResourceRecord) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "tenant_id": row.tenant_id,
            "project_id": row.project_id,
            "service_id": row.service_id,
            "environment": row.environment,
            "provider": row.provider,
            "provider_account_id": row.provider_account_id,
            "region": row.region,
            "provider_resource_id": row.provider_resource_id,
            "resource_type": row.resource_type,
            "display_name": row.display_name,
            "status": row.status,
            "tags": row.tags or {},
            "owner": row.owner,
            "configuration": row.configuration or {},
            "health": row.health or {},
            "cost": row.cost or {},
            "discovered_at": row.discovered_at.isoformat() if isinstance(row.discovered_at, datetime) else None,
            "updated_at": row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else None,
            "version": row.version,
        }

    @staticmethod
    def relationship_payload(row: ResourceRelationshipRecord) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "tenant_id": row.tenant_id,
            "project_id": row.project_id,
            "source_resource_id": row.source_resource_id,
            "target_resource_id": row.target_resource_id,
            "relationship_type": row.relationship_type,
            "source": row.source,
            "confidence": float(row.confidence or 0.0),
            "owner_confirmed": bool(row.owner_confirmed),
            "discovered_at": row.discovered_at.isoformat() if isinstance(row.discovered_at, datetime) else None,
        }

    @staticmethod
    def onboarding_payload(row: ServiceOnboardingProfileRecord) -> dict[str, Any]:
        telemetry = dict(row.telemetry or {})
        return {
            "id": str(row.id),
            "tenant_id": row.tenant_id,
            "project_id": row.project_id,
            "service_id": row.service_id,
            "environment": row.environment,
            "template_id": row.template_id,
            "onboarding_state": row.onboarding_state,
            "business_criticality": row.business_criticality,
            "owners": row.owners or [],
            "support_groups": row.support_groups or [],
            "connection_ids": row.connection_ids or [],
            "monitoring_sources": telemetry.get("monitoring_sources", []),
            "log_sources": telemetry.get("log_sources", []),
            "metric_sources": telemetry.get("metric_sources", []),
            "trace_sources": telemetry.get("trace_sources", []),
            "event_sources": telemetry.get("event_sources", []),
            "slos": row.slos or [],
            "business_kpis": row.business_kpis or [],
            "change_sources": row.change_sources or [],
            "knowledge_refs": row.knowledge_refs or [],
            "diagnostic_capabilities": row.diagnostic_capabilities or [],
            "remediation_capabilities": row.remediation_capabilities or [],
            "validation_rules": row.validation_rules or [],
            "escalation_policies": row.escalation_policies or [],
            "hitl_policy": row.hitl_policy or {},
            "dependencies": row.dependencies or [],
            "metadata": row.metadata_payload or {},
            "version": row.version,
            "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else None,
            "updated_at": row.updated_at.isoformat() if isinstance(row.updated_at, datetime) else None,
        }


def _score(*checks: bool) -> float:
    if not checks:
        return 0.0
    return round(sum(1 for check in checks if check) / len(checks), 4)
