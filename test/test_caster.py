import asyncio
import logging
import os
import pathlib
from os.path import dirname, realpath

import pytest
from suthing import FileHandle

from graflo.architecture.pipeline.runtime.actor import ActorWrapper
from graflo.hq.caster import Caster
from graflo.hq.ingestion_parameters import IngestionParams
from graflo.plot.plotter import assemble_tree
from test.conftest import fetch_manifest_obj, verify

logger = logging.getLogger(__name__)


@pytest.fixture()
def current_path():
    return dirname(realpath(__file__))


@pytest.fixture(scope="function")
def modes():
    return [("kg", "json"), ("ibes", "csv")]


def cast(modes, current_path, level, reset, n_cores=1):
    for mode, ext in modes:
        # work with main resource
        resource_name = mode.split("_")[0]
        manifest = fetch_manifest_obj(mode)
        schema = manifest.require_schema()
        ingestion_model = manifest.require_ingestion_model()

        # Every resource assembles into an actor tree; rendering it is
        # covered by test/plot.
        for r in ingestion_model.resources:
            assert assemble_tree(ActorWrapper(*r.pipeline)).number_of_nodes() > 0
        ingestion_model.finish_init(schema.core_schema)
        caster = Caster(
            schema,
            ingestion_model,
            ingestion_params=IngestionParams(n_cores=n_cores),
        )

        if level == 0:
            fname = os.path.join(
                current_path,
                f"./data/{mode}",
                f"{mode}.{ext}.gz",
            )

            asyncio.run(
                caster.process_resource(
                    resource_instance=pathlib.Path(fname), resource_name=resource_name
                )
            )
        else:
            data_obj = FileHandle.load_resource(
                f"test.data.{mode}",
                f"{mode}.{ext}.gz",
            )

            if level == 1:
                asyncio.run(
                    caster.process_resource(
                        resource_instance=data_obj, resource_name=resource_name
                    )
                )
            elif level == 2:
                data = caster.normalize_resource(data_obj)
                result = asyncio.run(
                    caster.cast_normal_resource(data, resource_name=resource_name)
                )
                graph = result.graph

                graph.pick_unique()

                vc = {k: len(v) for k, v in graph.items()}
                verify(
                    vc,
                    current_path=current_path,
                    mode=mode,
                    test_type="cast",
                    reset=reset,
                )


def test_cast(modes, current_path, reset):
    cast(modes, current_path, level=0, reset=reset)
    cast(modes, current_path, level=1, reset=reset)
    cast(modes, current_path, level=2, reset=reset)
    cast(modes, current_path, level=2, reset=reset, n_cores=4)
