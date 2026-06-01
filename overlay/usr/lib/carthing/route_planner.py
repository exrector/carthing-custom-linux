"""Route planner for the Car Thing session graph."""

from __future__ import annotations

from route_graph import Capability, Constraint, PlannedSession, Route


class RoutePlanError(RuntimeError):
    pass


class RoutePlanner:
    def __init__(self, registry):
        self.registry = registry

    def plan_simple_route(self, input_device_id, output_device_id, name="custom"):
        input_device = self.registry.by_id(input_device_id)
        output_device = self.registry.by_id(output_device_id)
        if input_device is None:
            raise RoutePlanError(f"unknown input device: {input_device_id}")
        if output_device is None:
            raise RoutePlanError(f"unknown output device: {output_device_id}")

        input_endpoint = self._first_endpoint(input_device.input_endpoints(), Capability.AUDIO_INPUT)
        output_endpoint = self._first_endpoint(output_device.output_endpoints(), Capability.AUDIO_OUTPUT)
        if input_endpoint is None:
            raise RoutePlanError(f"device has no audio input endpoint: {input_device.name}")
        if output_endpoint is None:
            raise RoutePlanError(f"device has no audio output endpoint: {output_device.name}")
        if not input_endpoint.protocols:
            raise RoutePlanError(f"input endpoint has no protocols: {input_device.name}/{input_endpoint.id}")
        if not output_endpoint.protocols:
            raise RoutePlanError(f"output endpoint has no protocols: {output_device.name}/{output_endpoint.id}")

        session = PlannedSession(
            name=name,
            routes=[
                Route(
                    input_device_id=input_device.id,
                    input_endpoint_id=input_endpoint.id,
                    output_device_id=output_device.id,
                    output_endpoint_id=output_endpoint.id,
                    control_backchannel=bool(output_device.control_endpoints()),
                )
            ],
        )
        session.required_protocols.update(input_endpoint.protocols)
        session.required_protocols.update(output_endpoint.protocols)
        session.constraints.update(input_device.constraints)
        session.constraints.update(output_device.constraints)

        if input_device.id == output_device.id:
            if self._has_constraint(session.constraints, Constraint.FULL_DUPLEX_FORBIDDEN):
                raise RoutePlanError(
                    "route rejected: same device cannot be both input and output "
                    "(full_duplex_forbidden)"
                )
            session.warnings.append("input and output are the same device; full-duplex constraints must be checked")
        if self._has_constraint(output_device.constraints, Constraint.CONTROL_BACKCHANNEL_ONLY):
            has_control = bool(output_device.control_endpoints())
            if not has_control:
                session.warnings.append(
                    "output device requires control backchannel but exposes no control endpoint"
                )
        self._check_conflicts(session, input_device, output_device, input_endpoint, output_endpoint)

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

    def _check_conflicts(self, session, input_device, output_device, input_endpoint, output_endpoint):
        input_constraints = self._constraint_values(input_device.constraints)
        output_constraints = self._constraint_values(output_device.constraints)
        merged_constraints = input_constraints | output_constraints
        input_protocols = self._protocol_values(input_endpoint.protocols)
        output_protocols = self._protocol_values(output_endpoint.protocols)

        if (
            Constraint.EXCLUSIVE_HCI.value in input_constraints
            and Constraint.EXCLUSIVE_HCI.value in output_constraints
            and input_device.id != output_device.id
        ):
            raise RoutePlanError("route rejected: both devices require exclusive hci0 resource")

        if (
            Constraint.EXCLUSIVE_A2DP_SOURCE.value in input_constraints
            and "classic_a2dp_source" in output_protocols
        ):
            raise RoutePlanError("route rejected: output requires a2dp_source while input keeps it exclusive")

        if (
            Constraint.EXCLUSIVE_A2DP_SINK.value in output_constraints
            and "classic_a2dp_sink" in input_protocols
        ):
            raise RoutePlanError("route rejected: input requires a2dp_sink while output keeps it exclusive")

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
