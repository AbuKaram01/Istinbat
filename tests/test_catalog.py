# SPDX-FileCopyrightText: 2026 AbuKaram01
# SPDX-License-Identifier: AGPL-3.0-or-later

import pytest

from istinbat.core.catalog import (
    EMBEDDER,
    LLM_FAMILIES,
    LLM_QUANTS,
    LLMS,
    RERANKER,
    ModelKind,
    ModelOption,
    RemoteFile,
    all_options,
    llms_of,
    option_by_key,
)
from istinbat.core.settings import PathsConfig


def test_the_catalog_offers_exactly_the_requested_models():
    assert EMBEDDER.repo == "BAAI/bge-m3" and RERANKER.repo == "BAAI/bge-reranker-v2-m3"
    assert [option.key for option in LLMS] == [
        "llm.e2b.q4_k_xl", "llm.e2b.q6_k_xl", "llm.e2b.q8_k_xl",
        "llm.e4b.q4_k_xl", "llm.e4b.q6_k_xl", "llm.e4b.q8_k_xl",
    ]
    assert LLM_FAMILIES == ("E2B", "E4B") and LLM_QUANTS == ("Q4_K_XL", "Q6_K_XL", "Q8_K_XL")
    assert len(all_options()) == 8


@pytest.mark.parametrize("family", ["E2B", "E4B"])
@pytest.mark.parametrize("quant", ["Q4_K_XL", "Q6_K_XL", "Q8_K_XL"])
def test_each_language_model_is_an_unsloth_gguf_with_the_dynamic_quantization(family, quant):
    (option,) = [o for o in LLMS if o.family == family and o.quant == quant]
    assert option.kind is ModelKind.LLM
    assert option.repo == f"unsloth/gemma-4-{family}-it-GGUF"
    assert [file.path for file in option.files] == [f"gemma-4-{family}-it-UD-{quant}.gguf"]
    assert option.entry == option.files[0].path


def test_language_models_of_one_family_share_a_folder_but_not_a_file():
    e2b = llms_of("E2B")
    assert len(e2b) == 3 and len({o.directory for o in e2b}) == 1 and len({o.entry for o in e2b}) == 3
    assert {o.directory for o in e2b}.isdisjoint({o.directory for o in llms_of("E4B")})


def test_larger_quantizations_and_the_larger_family_are_bigger_downloads():
    sizes = [option.approx_bytes for option in LLMS]
    assert sizes[:3] == sorted(sizes[:3]) and sizes[3:] == sorted(sizes[3:])
    assert min(sizes[3:]) > min(sizes[:3])


def test_only_the_files_needed_to_run_each_model_are_listed():
    names = {f.path for option in (EMBEDDER, RERANKER) for f in option.files}
    assert not any(name.startswith(("onnx", "imgs", "assets")) or name.endswith((".jpg", ".md")) for name in names)
    assert "pytorch_model.bin" in {f.path for f in EMBEDDER.files} and "1_Pooling/config.json" in {
        f.path for f in EMBEDDER.files}                                  # Without it the pooling would be wrong.
    assert "model.safetensors" in {f.path for f in RERANKER.files}


def test_the_embedder_and_reranker_settings_point_at_their_folder_and_the_llm_at_its_file(tmp_path):
    assert EMBEDDER.local_path(tmp_path) == tmp_path / "bge-m3"
    assert RERANKER.local_path(tmp_path) == tmp_path / "bge-reranker-v2-m3"
    llm = option_by_key("llm.e4b.q6_k_xl")
    assert llm.local_path(tmp_path) == tmp_path / "gemma-4-E4B-it" / "gemma-4-E4B-it-UD-Q6_K_XL.gguf"


def test_each_kind_names_a_real_settings_field():
    fields = set(PathsConfig.__dataclass_fields__)
    assert {kind.settings_attribute for kind in ModelKind} <= fields


def test_an_option_counts_as_downloaded_only_when_every_file_exists(tmp_path):
    option = ModelOption(
        "x", ModelKind.EMBEDDER, "o/r", "x", (RemoteFile("a.json", 1), RemoteFile("sub/b.bin", 1)),
    )
    assert not option.is_downloaded(tmp_path)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "a.json").write_text("{}")
    assert not option.is_downloaded(tmp_path)
    (tmp_path / "x" / "sub").mkdir()
    (tmp_path / "x" / "sub" / "b.bin.part").write_bytes(b"half")         # A partial file is not a download.
    assert not option.is_downloaded(tmp_path)
    (tmp_path / "x" / "sub" / "b.bin").write_bytes(b"full")
    assert option.is_downloaded(tmp_path)


@pytest.mark.parametrize("path", ["../escape", "/abs/path", "a/../../b", ""])
def test_a_file_path_can_never_leave_the_model_folder(path):
    with pytest.raises(ValueError):
        RemoteFile(path, 1)


def test_unknown_keys_raise():
    with pytest.raises(KeyError):
        option_by_key("llm.e9b.q1")


def test_every_option_key_and_folder_is_unique_and_filesystem_safe():
    keys = [o.key for o in all_options()]
    assert len(keys) == len(set(keys))
    assert all("/" not in o.directory and o.directory not in {"", ".", ".."} for o in all_options())
