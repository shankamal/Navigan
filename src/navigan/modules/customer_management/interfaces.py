from typing import Protocol


class ProviderDependencies(Protocol):
    def has_dependencies(self, customer_id: str, provider_code: str) -> bool: ...


class NoEnvironmentModule:
    """Bootstrap adapter only: replace before enabling Environment Management."""

    def has_dependencies(self, customer_id: str, provider_code: str) -> bool:
        return False
