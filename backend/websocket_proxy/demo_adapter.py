"""Paper streaming has no upstream connection or transport resources."""
from backend.websocket_proxy.base_adapter import BaseBrokerAdapter


class DemoAdapter(BaseBrokerAdapter):
    def setup_zmq(self) -> int:
        return 0  # The server fans out the existing synthetic cache directly.

    def connect(self) -> None:
        self._running = True

    def subscribe(self, symbols: list[dict], mode: int) -> None:
        pass  # The server owns the per-client subscription index.

    def unsubscribe(self, symbols: list[dict], mode: int) -> None:
        pass

    def disconnect(self) -> None:
        self._running = False
