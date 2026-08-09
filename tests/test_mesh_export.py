"""regression tests for two bugs that actually came up: uploading a textured
.obj failed with "no module named PIL", and meshes were rendering solid
black in the viewer.

root causes, checked directly rather than guessed at:
1. pillow wasn't in the dependency list - trimesh's OBJ/MTL loader needs it
   to decode a referenced texture image.
2. the exported GLB had no NORMAL attribute whatsoever (checked the raw
   glTF JSON myself - attributes was just {"POSITION": ...}). a PBR
   material has nothing to shade with in that case, renders black no
   matter what color the mesh is supposed to be.
3. a single uploaded .obj literally can't carry its own texture - OBJ
   references a sibling .mtl, which references the actual image file, both
   external to the .obj itself. uploading just the .obj with no resolver
   makes trimesh quietly swap in a meaningless 2x2 placeholder instead of
   erroring, which just looks like "texture didn't show up". upload
   endpoint now takes the .obj plus its .mtl/image together and resolves
   them properly.
"""

import json
import struct
from pathlib import Path

import numpy as np
import pytest
import trimesh
from fastapi.testclient import TestClient
from PIL import Image

from api.main import app

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = REPO_ROOT / "src" / "craniumpy_core" / "templates" / "template_xy_com.ply"


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _parse_glb_json(glb_bytes: bytes) -> dict:
    json_len = struct.unpack("<I", glb_bytes[12:16])[0]
    return json.loads(glb_bytes[20 : 20 + json_len])


def _textured_box_obj_mtl_png() -> dict[str, bytes]:
    """small textured box as separate .obj/.mtl/.png bytes - the shape a real
    textured-OBJ upload actually arrives in. distinctive solid color so I can
    tell "the real texture" apart from trimesh's 2x2 placeholder. built by
    hand rather than through trimesh's own exporter - export_obj in this
    trimesh version only hands back the .obj text, no companion files, so
    there's no way to get a real .mtl/.png pair out of it."""
    box = trimesh.creation.box(extents=[10, 10, 10])
    uv = np.random.default_rng(0).random((len(box.vertices), 2))
    obj_lines = ["mtllib material.mtl", "usemtl material_0"]
    for v in box.vertices:
        obj_lines.append(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
    for vt in uv:
        obj_lines.append(f"vt {vt[0]:.6f} {vt[1]:.6f}")
    for face in box.faces:
        a, b, c = (i + 1 for i in face)
        obj_lines.append(f"f {a}/{a} {b}/{b} {c}/{c}")
    obj_text = "\n".join(obj_lines) + "\n"

    mtl_text = "newmtl material_0\nmap_Kd texture.png\n"

    image = Image.new("RGB", (8, 8), (11, 22, 33))
    from io import BytesIO

    png_buffer = BytesIO()
    image.save(png_buffer, format="PNG")

    return {
        "model.obj": obj_text.encode(),
        "material.mtl": mtl_text.encode(),
        "texture.png": png_buffer.getvalue(),
    }


def test_glb_export_includes_normal_attribute(client: TestClient):
    with open(TEMPLATE_PATH, "rb") as f:
        upload = client.post("/api/sessions", files=[("files", ("template.ply", f, "application/octet-stream"))])
    session_id = upload.json()["session_id"]

    glb = client.get(f"/api/sessions/{session_id}/mesh/original")
    assert glb.status_code == 200
    gltf_json = _parse_glb_json(glb.content)
    attributes = gltf_json["meshes"][0]["primitives"][0]["attributes"]
    assert "NORMAL" in attributes


def test_textured_obj_with_companion_files_preserves_real_texture(client: TestClient):
    files = _textured_box_obj_mtl_png()
    upload = client.post(
        "/api/sessions",
        files=[("files", (name, data, "application/octet-stream")) for name, data in files.items()],
    )
    assert upload.status_code == 200, upload.text
    session_id = upload.json()["session_id"]

    glb = client.get(f"/api/sessions/{session_id}/mesh/original")
    assert glb.status_code == 200
    gltf_json = _parse_glb_json(glb.content)

    # a real material/texture made it through, wasn't silently dropped
    assert gltf_json.get("materials"), "expected a material in the exported GLB"
    assert gltf_json.get("images"), "expected an embedded texture image in the exported GLB"

    # and it's the real 8x8 image, not trimesh's 2x2 missing-texture
    # placeholder - proves the resolver actually found material.mtl + the
    # png instead of quietly substituting something else
    image_index = gltf_json["images"][0]
    buffer_view = gltf_json["bufferViews"][image_index["bufferView"]]
    offset = buffer_view.get("byteOffset", 0)
    length = buffer_view["byteLength"]

    json_len = struct.unpack("<I", glb.content[12:16])[0]
    bin_chunk_start = 20 + json_len + 8  # skip json chunk + next chunk's 8-byte header
    image_bytes = glb.content[bin_chunk_start + offset : bin_chunk_start + offset + length]
    decoded = Image.open(__import__("io").BytesIO(image_bytes))
    assert decoded.size == (8, 8)


def test_obj_upload_without_companion_files_still_succeeds(client: TestClient):
    """this is just documenting the fallback behavior: a lone .obj referencing
    a .mtl we don't have still uploads fine (trimesh substitutes a
    placeholder rather than erroring). not something I'm trying to fix,
    just making sure it doesn't regress into a hard failure."""
    files = _textured_box_obj_mtl_png()
    obj_only = {k: v for k, v in files.items() if k.endswith(".obj")}
    upload = client.post(
        "/api/sessions",
        files=[("files", (name, data, "application/octet-stream")) for name, data in obj_only.items()],
    )
    assert upload.status_code == 200, upload.text


def test_upload_rejects_zero_or_multiple_mesh_files(client: TestClient):
    # Only companion files, no primary mesh file.
    response = client.post("/api/sessions", files=[("files", ("material.mtl", b"", "text/plain"))])
    assert response.status_code == 400

    # Two primary mesh files at once is ambiguous.
    response = client.post(
        "/api/sessions",
        files=[
            ("files", ("a.ply", b"", "application/octet-stream")),
            ("files", ("b.ply", b"", "application/octet-stream")),
        ],
    )
    assert response.status_code == 400
