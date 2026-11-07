"""Drag-defined geometry stored as precise, editable native ink paths."""
import math
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QGuiApplication

SHAPES = (('line', '直线'), ('arrow', '箭头'), ('rectangle', '矩形'),
          ('ellipse', '椭圆'), ('triangle', '三角形'), ('diamond', '菱形'))


def shape_points(kind, start, end, width=2., constrained=False, bounds=None):
    if kind not in dict(SHAPES):
        raise ValueError('未知图形')
    if not all(math.isfinite(v) for v in (*start, *end, width)) or width <= 0:
        raise ValueError('图形坐标或线宽无效')
    ax, ay = start
    dx, dy = end[0]-ax, end[1]-ay
    if constrained:
        if kind in ('line', 'arrow'):
            angle = round(math.atan2(dy, dx)/(math.pi/4))*(math.pi/4)
            length = math.hypot(dx, dy)
            dx, dy = length*math.cos(angle), length*math.sin(angle)
            if bounds:
                fraction = 1.
                for origin, delta, limit in ((ax, dx, bounds[0]), (ay, dy, bounds[1])):
                    if delta > 1e-10: fraction = min(fraction, (limit-origin)/delta)
                    elif delta < -1e-10: fraction = min(fraction, -origin/delta)
                dx, dy = dx*max(0., fraction), dy*max(0., fraction)
        else:
            side = max(abs(dx), abs(dy))
            if bounds:
                side = min(side, bounds[0]-ax if dx >= 0 else ax,
                           bounds[1]-ay if dy >= 0 else ay)
            dx, dy = math.copysign(side, dx), math.copysign(side, dy)
    end = (ax+dx, ay+dy)
    if kind in ('line', 'arrow'):
        length = math.hypot(dx, dy)
        if length < .01: return ()
        if kind == 'line': return (start, end)
        angle = math.atan2(dy, dx)
        wing = min(length*.4, max(5., width*5))
        wings = [(end[0]-wing*math.cos(angle+s*.45),
                  end[1]-wing*math.sin(angle+s*.45)) for s in (-1, 1)]
        if bounds:
            wings = [(max(0., min(bounds[0], x)), max(0., min(bounds[1], y)))
                     for x, y in wings]
        return (start, end, wings[0], end, wings[1])
    left, right = sorted((ax, end[0]))
    top, bottom = sorted((ay, end[1]))
    if min(right-left, bottom-top) < .01: return ()
    cx, cy = (left+right)/2, (top+bottom)/2
    if kind == 'rectangle':
        points = ((left, top), (right, top), (right, bottom), (left, bottom))
    elif kind == 'triangle':
        points = ((cx, top), (right, bottom), (left, bottom))
    elif kind == 'diamond':
        points = ((cx, top), (right, cy), (cx, bottom), (left, cy))
    else:
        rx, ry = (right-left)/2, (bottom-top)/2
        points = tuple((cx+rx*math.cos(i*math.tau/128),
                        cy+ry*math.sin(i*math.tau/128)) for i in range(128))
    return tuple(points)+(points[0],)


class ShapeDrawingMixin:
    def event(self, event):
        if (event.type() in (QEvent.Type.UngrabMouse, QEvent.Type.WindowDeactivate,
                             QEvent.Type.Hide, QEvent.Type.EnabledChange)
                and hasattr(self, 'edits') and self._shapeOperation() is not None
                and (event.type() != QEvent.Type.EnabledChange or not self.isEnabled())):
            self.edits.cancel()
            self.update()
        return super().event(event)

    def _shapeOperation(self):
        core = getattr(self.edits, 'core', self.edits)
        pending = core.pending
        return pending if pending is not None and '_shape_anchor' in pending else None

    def _beginShapeGesture(self, page, point, modifiers):
        self.edits.begin(page, point, 'draw', self.shape_width, self.shape_color, 'partial')
        core = getattr(self.edits, 'core', self.edits)
        core.pending.update(_shape_anchor=point, _shape_end=point,
                            _shape_kind=self.shape_kind, geometry_is_linear=True)
        self._reshapeGesture(bool(modifiers & Qt.KeyboardModifier.ShiftModifier))

    def _reshapeGesture(self, constrained):
        op = self._shapeOperation()
        if op is None: return
        page = self.edits.pending['page']
        op['points'] = list(shape_points(op['_shape_kind'], op['_shape_anchor'],
                                        op['_shape_end'], op['width'], constrained,
                                        self.editPageSize(page)))
        self.update()

    def _extendShapeGesture(self, position, modifiers=None):
        op = self._shapeOperation()
        if op is None: return False
        page = self.edits.pending['page']
        dw, dh = self.draw_sizes[page]
        nw, nh = self.editPageSize(page)
        point = ((position.x()-(self.width()-dw)/2)*nw/dw,
                 (position.y()-self.pageTop(page))*nh/dh)
        op['_shape_end'] = (max(0., min(nw, point[0])), max(0., min(nh, point[1])))
        if modifiers is None: modifiers = QGuiApplication.keyboardModifiers()
        self._reshapeGesture(bool(modifiers & Qt.KeyboardModifier.ShiftModifier))
        return True

    def _finishShapeGesture(self):
        op = self._shapeOperation()
        if op is None: return
        if not op['points']:
            self.edits.cancel()
            return
        for key in ('_shape_anchor', '_shape_end', '_shape_kind'):
            op.pop(key, None)

    def focusOutEvent(self, event):
        if hasattr(self, 'edits') and self._shapeOperation() is not None:
            self.edits.cancel()
            self.update()
        super().focusOutEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Shift and self._shapeOperation() is not None:
            self._reshapeGesture(False)
            event.accept()
        else:
            super().keyReleaseEvent(event)
