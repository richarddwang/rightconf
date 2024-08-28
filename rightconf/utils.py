from collections.abc import Mapping
from os import PathLike

from omegaconf import DictConfig, OmegaConf


def load_configuration(
    config_files: list[PathLike],
    cli_args: list[str],
) -> DictConfig:
    # Check
    for cli_arg in cli_args:
        assert "=" in cli_arg, f'Invalid argugment "{cli_arg}" for Omegaconf CLI.'

    # Merge configurations from different sources
    configs = []
    for config_file in config_files:
        config = OmegaConf.load(config_file)
        configs.append(config)
    configs.append(OmegaConf.from_cli(cli_args))
    config = OmegaConf.merge(*configs)
    return config


def get_object_kwargs(config):
    return {k: v for k, v in OmegaConf.to_object(config).items() if k != "OBJECT"}


def flatten(dictionary: dict, parent_key="", sep=".") -> dict:
    items = []
    for key, value in dictionary.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else key
        if isinstance(value, Mapping):
            items.extend(flatten(value, new_key, sep=sep).items())
        else:
            items.append((new_key, value))
    return dict(items)
