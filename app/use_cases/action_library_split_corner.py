try:
    from ...core.action_library_split_corner import split_corner
except ImportError:
    from core.action_library_split_corner import split_corner


def split_scp_by_corner(context):
    _result, error = split_corner(context)
    return (not error), error
