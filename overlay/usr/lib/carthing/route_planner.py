"""Route planner for the Car Thing session graph."""

from __future__ import annotations

from route_graph import Capability, PlannedSession, Route


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
            session.warnings.append("input and output are the same device; full-duplex constraints must be checked")

        return session

    @staticmethod
    def _first_endpoint(endpoints, capability):
        for endpoint in endpoints:
            if endpoint.supports(capability):
                return endpoint
        return endpoints[0] if endpoints else None

