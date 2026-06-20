"""Route planner for the Car Thing session graph."""

from __future__ import annotations

from route_graph import Capability, Constraint, PlannedSession, Route


class RoutePlanError(RuntimeError):
    pass


class RoutePlanner:
    def __init__(self, registry):
        self.registry = registry

    def plan_simple_route(self, source_device_id, sink_device_id, name="custom"):
        source_device = self.registry.by_id(source_device_id)
        sink_device = self.registry.by_id(sink_device_id)
        if source_device is None:
            raise RoutePlanError(f"unknown source device: {source_device_id}")
        if sink_device is None:
            raise RoutePlanError(f"unknown sink device: {sink_device_id}")

        source_endpoint = self._first_endpoint(source_device.input_endpoints(), Capability.AUDIO_INPUT)
        sink_endpoint = self._first_endpoint(sink_device.output_endpoints(), Capability.AUDIO_OUTPUT)
        if source_endpoint is None:
            raise RoutePlanError(f"device has no audio source endpoint: {source_device.name}")
        if sink_endpoint is None:
            raise RoutePlanError(f"device has no audio sink endpoint: {sink_device.name}")
        if not source_endpoint.protocols:
            raise RoutePlanError(f"source endpoint has no protocols: {source_device.name}/{source_endpoint.id}")
        if not sink_endpoint.protocols:
            raise RoutePlanError(f"sink endpoint has no protocols: {sink_device.name}/{sink_endpoint.id}")

        session = PlannedSession(
            name=name,
            routes=[
                Route(
                    source_device_id=source_device.id,
                    source_endpoint_id=source_endpoint.id,
                    sink_device_id=sink_device.id,
                    sink_endpoint_id=sink_endpoint.id,
                    control_backchannel=bool(sink_device.control_endpoints()),
                )
            ],
        )
        session.required_protocols.update(source_endpoint.protocols)
        session.required_protocols.update(sink_endpoint.protocols)
        session.constraints.update(source_device.constraints)
        session.constraints.update(sink_device.constraints)

        if source_device.id == sink_device.id:
            if self._has_constraint(session.constraints, Constraint.FULL_DUPLEX_FORBIDDEN):
                raise RoutePlanError(
                    "route rejected: same device cannot be both source and sink "
                    "(full_duplex_forbidden)"
                )
            session.warnings.append("source and sink are the same device; full-duplex constraints must be checked")
        if self._has_constraint(sink_device.constraints, Constraint.CONTROL_BACKCHANNEL_ONLY):
            has_control = bool(sink_device.control_endpoints())
            if not has_control:
                session.warnings.append(
                    "sink device requires control backchannel but exposes no control endpoint"
                )
        self._check_conflicts(session, source_device, sink_device, source_endpoint, sink_endpoint)

        return session

    @staticmethod
    def _first_endpoint(endpoints, capability):
        for endpoint in endpoints:
            if endpoint.supports(capability):
                return endpoint
        return endpoints[0] if endpoints else None

    @staticmethod
    def _has_constraint(constraints, constraint):
        target = constraint.value if hasattr(constraint, "value") else str(constraint)
        for value in constraints:
            current = value.value if hasattr(value, "value") else str(value)
            if current == target:
                return True
        return False

    def _check_conflicts(self, session, source_device, sink_device, source_endpoint, sink_endpoint):
        source_constraints = self._constraint_values(source_device.constraints)
        sink_constraints = self._constraint_values(sink_device.constraints)
        merged_constraints = source_constraints | sink_constraints
        source_protocols = self._protocol_values(source_endpoint.protocols)
        sink_protocols = self._protocol_values(sink_endpoint.protocols)

        if (
            Constraint.EXCLUSIVE_HCI.value in source_constraints
            and Constraint.EXCLUSIVE_HCI.value in sink_constraints
            and source_device.id != sink_device.id
        ):
            raise RoutePlanError("route rejected: both devices require exclusive hci0 resource")

        if (
            Constraint.EXCLUSIVE_A2DP_SOURCE.value in source_constraints
            and "classic_a2dp_source" in sink_protocols
        ):
            raise RoutePlanError("route rejected: sink requires a2dp_source while source keeps it exclusive")

        if (
            Constraint.EXCLUSIVE_A2DP_SINK.value in sink_constraints
            and "classic_a2dp_sink" in source_protocols
        ):
            raise RoutePlanError("route rejected: source requires a2dp_sink while sink keeps it exclusive")

        if Constraint.REQUIRES_STOP_BEFORE_START.value in merged_constraints:
            session.warnings.append("route requires stop-before-start transition")

    @staticmethod
    def _constraint_values(values):
        result = set()
        for value in values:
            result.add(value.value if hasattr(value, "value") else str(value))
        return result

    @staticmethod
    def _protocol_values(values):
        result = set()
        for value in values:
            result.add(value.value if hasattr(value, "value") else str(value))
        return result
