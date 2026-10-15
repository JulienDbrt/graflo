"""NebulaConfig read from the docker environment file."""

from graflo.connections.onto import NebulaConfig


def test_nebula_config_from_docker_env():
    cfg = NebulaConfig.from_docker_env()
    assert cfg.username == "root"
    assert cfg.password == "test!passfortesting"
    assert cfg.version == "3"
