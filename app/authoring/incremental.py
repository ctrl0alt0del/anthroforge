"""Reuse evaluated entities only when their inputs and scene are unchanged."""
from ...core.authoring.codec import digest


def reusable(document,previous,snapshot):
    if not previous or previous["scene_revision"] != snapshot.revision:
        return {}
    old = previous["document"]
    shared = ("context","targets","frames","regions","sources")
    if any(document[key] != old[key] for key in shared):
        return {}
    return {name:output for name,output in previous["results"].items()
            if name in document["muscles"] and signature(document,name) == signature(old,name)}


def signature(document,name):
    muscle = document["muscles"][name]
    return digest([muscle,document["recipes"][muscle["recipe"]],document["policies"][muscle["policy"]],
                   document["volume_presets"][muscle["volume_preset"]]])
