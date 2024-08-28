from abc import abstractmethod
from argparse import ArgumentParser, Namespace
from types import ModuleType
from typing import Any, Type, Optional

from omegaconf import DictConfig


class ConfigurationRunnerInterface:
    @property
    @abstractmethod
    def modules(self) -> list[ModuleType]:
        """Modules where the object path starts with.
        Note it is important to make it a user-defined function rather than a argument to initialization,
        because module type are not pickable and thus can't be used in parallel sweep and import module
        from module paths causes lots of unexpected troubles.
        """

    def extend_cli(self, parser: ArgumentParser) -> None: ...

    def postprocess(self, args: Namespace, config: DictConfig) -> None: ...

    @abstractmethod
    def run(self, args: Namespace, config: DictConfig, log_config: dict) -> None: ...

    def main() -> None: ...

    def instantiate_object(
        self,
        object_config: DictConfig,
        subobject_kwargs: Optional[dict[Type, dict[str, Any]]] = None,
        **object_kwargs,
    ) -> Any: ...
