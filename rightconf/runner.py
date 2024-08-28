import inspect
import itertools
import multiprocessing as mp
import re
from abc import abstractmethod
from argparse import ArgumentParser, Namespace
from multiprocessing import Pool
from os import PathLike
from types import ModuleType
from typing import (
    Any,
    Optional,
    Type,
)

from omegaconf import DictConfig, ListConfig, OmegaConf

from .abstraction import ConfigurationRunnerInterface
from .signature import Parser
from .types import is_specifiable_type
from .utils import flatten, load_configuration


class ConfigurationRunner(ConfigurationRunnerInterface):
    def __init__(
        self,
        default_config_files: Optional[list[PathLike]] = None,
        skip_logging: Optional[list[str]] = None,
    ):
        self.default_config_files = default_config_files or []
        self.regex_skip = "|".join(skip_logging) if skip_logging else None
        self.parser = Parser()

    @property
    @abstractmethod
    def modules(self) -> list[ModuleType]: ...

    @property
    def modules_dict(self) -> dict[str, ModuleType]:
        return {module.__name__.split(".")[-1]: module for module in self.modules}

    def main(self):
        # Command line interface
        args, rest_args = self._parse_cli()

        # Load the configurations from files and CLI
        config = load_configuration(
            config_files=[*self.default_config_files, *args.config],
            cli_args=rest_args,
        )

        # Realize all the overwrites for each run in the sweep
        config_sweep = config.pop("SWEEP", None)
        omegaconfcli_strings = (
            (self._convert_sweep_to_cli_strings(config_sweep)) if config_sweep else [""]
        )

        if args.dry:
            self._process_object_configuration(config)
            self.postprocess(args, config)
            print(OmegaConf.to_yaml(config))
            if config_sweep:
                for i, omegaconfcli_string in enumerate(omegaconfcli_strings):
                    print(f"Run {i}: {omegaconfcli_string}")
            return

        # Realize all configs
        configs, log_configs = [], []
        for omegaconfcli_string in omegaconfcli_strings:
            _config = OmegaConf.create(config)  # clone
            if omegaconfcli_string:
                _config = OmegaConf.merge(
                    _config,
                    OmegaConf.from_cli(omegaconfcli_string.split(" ")),
                )
            self._process_object_configuration(_config)
            self.postprocess(args, _config)
            configs.append(_config)
            log_configs.append(self.create_log_config(_config))

        # Run
        self._run_configs(
            args,
            configs,
            log_configs,
            omegaconfcli_strings,
        )

    def _parse_cli(self):
        parser = ArgumentParser()
        parser.add_argument(
            "-c",
            "--config",
            action="append",
            help="The Omegaconf configuration YAML file to load. You can repeat this flag to specify multiple files to load. If there are conflicts between files, the value specified by the latter file is taken.",
        )
        parser.add_argument(
            "-msw",
            "--max-sweep-workers",
            type=int,
            default=None,
            help="Max number of parallel workers for the sweeping process, which can be larger or smaller than the number of configurations to be swept. If there is not specified, sweep is done sequentially.",
        )
        parser.add_argument(
            "--dry",
            action="store_true",
            help="Only print the final configuration for check and exist.",
        )
        self.extend_cli(parser)
        return parser.parse_known_args()

    def _convert_sweep_to_cli_strings(
        self, sweep: DictConfig, product: bool = True
    ) -> list[str]:
        nested_omegastrs: list[list[str]] = []
        for key, domain in sweep.items():
            if key.startswith("GROUP"):
                candidate_omegastrs = self._convert_sweep_to_cli_strings(domain, False)
            else:
                _msg = "In Sweep, candidate values for {key} should be list, but got {domain}"
                assert isinstance(domain, ListConfig), _msg
                candidate_omegastrs = [f"{key}={val}" for val in domain]
            nested_omegastrs.append(candidate_omegastrs)

        omegastrs = []
        link_fn = itertools.product if product else zip
        for linked_omegastrs in link_fn(*nested_omegastrs):
            omegastr = " ".join(linked_omegastrs)
            omegastrs.append(omegastr)

        return omegastrs

    def _process_object_configuration(self, config: DictConfig | ListConfig):
        # Recursively process
        values = config.values() if isinstance(config, DictConfig) else config
        for value in values:
            if isinstance(value, DictConfig | ListConfig):
                self._process_object_configuration(config=value)
        if isinstance(config, ListConfig) or "OBJECT" not in config:
            return

        # Get signature
        obj = eval(config.OBJECT, self.modules_dict)
        if inspect.isfunction(obj):
            fn, cls = obj, None
        else:
            fn, cls = obj.__init__, obj
        parameters = self.parser.resolve_signature(fn, cls, self.modules_dict)

        # Validation
        ## Prohibit exessive arguments to prevent unawared argument name typo.
        for key, value in config.items():
            if key != "OBJECT" and key not in parameters:
                raise KeyError(
                    f'"{key}" does not match any arguments for "{str(obj)}": {str(list(parameters.keys()))}'
                )

        # Set defaults
        for name, param in parameters.items():
            if (
                param.default is not inspect._empty
                and not name.startswith("_")
                and not name.endswith("kwargs")
                and is_specifiable_type(param.annotation)
                and is_specifiable_type(type(param.default))
            ):
                config.setdefault(name, param.default)

    def create_log_config(self, config: DictConfig) -> dict:
        log_config = {}
        for key, value in flatten(config).items():
            if self.regex_skip and re.fullmatch(self.regex_skip, key):
                continue
            if key.endswith("OBJECT"):
                value = value.split(".")[-1]
            log_config[key] = value
        return log_config

    def _run_configs(
        self,
        args: Namespace,
        configs: list[DictConfig],
        log_configs: list[dict],
        omegaconfcli_strings: list[str],
    ) -> None:
        # Realize all arguments in advance
        all_args = [
            (args, config, log_config, omegaconfcli_string)
            for config, log_config, omegaconfcli_string in zip(
                configs,
                log_configs,
                omegaconfcli_strings,
            )
        ]

        # Run parallely or sequentailly
        if args.max_sweep_workers:
            if args.max_sweep_workers < len(configs):
                _msg = f"\n\nNumber of sweep workers {args.max_sweep_workers} is less than number of configuratons to be swept {len(configs)}.\nEnsure you won't modify code during execution, otherwise the newly swept configurtion will run on the modified code. \nPress any key to conitnue:"
                input(_msg)
            mp.set_start_method("spawn")
            with Pool(min(args.max_sweep_workers, len(configs))) as pool:
                pool.starmap(self._run_config, all_args)
        else:
            for args in all_args:
                self._run_config(*args)

    def _run_config(
        self,
        args: Namespace,
        config: DictConfig,
        log_config: dict,
        omegaconfcli_string: str,
    ) -> None:
        if omegaconfcli_string:
            print(f"\nCurrent configuration: {omegaconfcli_string}\n")
        self.run(args, config, log_config)

    def instantiate_object(
        self,
        object_config: DictConfig,
        subobject_kwargs: Optional[dict[Type, dict[str, Any]]] = None,
        **object_kwargs,
    ) -> Any:
        _msg = f"There is not `OBJECT` keyword to specify the class or function path in {OmegaConf.to_yaml(object_config)}"
        assert "OBJECT" in object_config, _msg
        return self._instantiate_object(
            object_config,
            objects_kwargs=subobject_kwargs or {},
            **object_kwargs,
        )

    def _instantiate_object(
        self,
        node: DictConfig | ListConfig | Any,
        objects_kwargs: dict[Type, dict[str, Any]],
        **kwargs,
    ) -> dict | list | Any:
        if isinstance(node, ListConfig):
            return [self._instantiate_object(value, objects_kwargs) for value in node]
        elif isinstance(node, DictConfig):
            node_kwargs = {}
            for key, value in node.items():
                if key != "OBJECT":
                    if isinstance(value, DictConfig | ListConfig):
                        value = self._instantiate_object(value, objects_kwargs)
                    node_kwargs[key] = value
            if "OBJECT" in node:
                cls = eval(node.OBJECT, self.modules_dict)
                object_kwargs = objects_kwargs.get(cls, {})
                return cls(**(node_kwargs | object_kwargs | kwargs))
            else:
                return node_kwargs
        else:
            return node
