class ShapeDeformer:
    priority = 100

    def forward(self, p, _shape):
        return p

    def inverse(self, p, _shape):
        return p


class MirrorDeformer(ShapeDeformer):
    # Mirror is orchestrated by mirror sync/controller at object level.
    # Keep this in pipeline for explicit priority ordering.
    priority = 10


class ResolutionDeformer(ShapeDeformer):
    # Resolution affects mesh tessellation, not single point coordinates.
    priority = 30

