class Attachment:
    """
    Represents parametric attachment to a parent SCP.
    """

    def __init__(self, parent_id: str, param):
        self.parent_id = parent_id
        self.param = param  # shape-specific parameter
