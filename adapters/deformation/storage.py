"""References travel with the root and mesh through Blender datablock pointers."""
import bpy
from ...core.deformation.serialization import encode, decode

KEY = "af_deformation_reference"


def load(root, obj):
    block = obj.get(KEY)
    if block is None or block != root.get(KEY):
        raise ValueError("Missing or mismatched deformation reference; initialize explicitly.")
    if not isinstance(block, bpy.types.Text):
        raise ValueError("Invalid deformation reference datablock.")
    reference = decode(block.as_string().replace("\n", "").replace("\r", ""))
    if block.get("af_content_signature") != reference.signature:
        raise ValueError("Deformation reference datablock signature mismatch.")
    return reference


def store(root, obj, reference):
    payload = encode(reference)
    verified = decode(payload)
    block = bpy.data.texts.new("AF_DEFORMATION_REFERENCE")
    try:
        block.write("\n".join(payload[i:i+120] for i in range(0,len(payload),120)))
        block.use_fake_user = True
        block["af_content_signature"] = verified.signature
        assign(root, obj, block)
    except Exception:
        bpy.data.texts.remove(block); raise
    return block


def assign(root, obj, block):
    entries = ((root,KEY,block),(obj,KEY,block),(root,"af_deformation_mesh",obj),(obj,"af_deformation_root",root))
    previous = [(owner,key,owner.get(key)) for owner,key,_ in entries]
    try:
        for owner,key,value in entries: owner[key] = value
    except Exception:
        for owner, key, value in previous:
            if value is None:
                if key in owner: del owner[key]
            else:
                owner[key] = value
        raise
