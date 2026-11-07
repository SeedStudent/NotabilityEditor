"""Uniform, page-bounded ink resizing with a disposable gesture preview."""
import math
from dataclasses import replace
from PyQt6.QtCore import QPointF, QRectF, Qt, QEvent
from PyQt6.QtGui import QTransform


def scale_stroke(stroke, factor, anchor):
    if (not math.isfinite(factor) or factor <= 0
            or not all(math.isfinite(v) for v in anchor)):
        raise ValueError('笔迹缩放比例或中心无效')
    if abs(factor-1.) < 1e-10:return stroke
    ax, ay = anchor
    # Freeze the displayed curve before changing its size. Re-running a
    # width-dependent capture smoother would change small corners on resize.
    points = stroke.points if stroke.geometry_is_linear or stroke.outline is not None else stroke.erasure_points
    return replace(stroke, points=tuple((ax+(x-ax)*factor, ay+(y-ay)*factor) for x, y in points),
                   width=stroke.width*factor, geometry_is_linear=True,
                   outline=(tuple((x*factor, y*factor) for x, y in stroke.outline)
                            if stroke.outline is not None else None))


def scaled_rect(bounds, factor, anchor):
    return QRectF(anchor[0]+(bounds.x()-anchor[0])*factor,
                  anchor[1]+(bounds.y()-anchor[1])*factor,
                  bounds.width()*factor, bounds.height()*factor)


def scale_region(region, factor, anchor):
    transform=QTransform()
    transform.translate(*anchor);transform.scale(factor,factor);transform.translate(-anchor[0],-anchor[1])
    return transform.map(region)


class SelectionResizeMixin:
    def _selectionHandleAt(self, position):
        if self.edit_tool!='select' or not self.show_ink or position is None:return None
        bounds=self.selectionBounds()
        if bounds is None:return None
        page=self.selection_page
        nw,nh=self.editPageSize(page);dw,dh=self.draw_sizes[page]
        rect=bounds.adjusted(-3,-3,3,3)
        center_x=(self.width()-dw)/2+rect.center().x()*dw/nw
        center_y=self.pageTop(page)+rect.center().y()*dh/nh
        # A tiny dot's handles overlap. Keep its center available for moving.
        if (rect.width()*dw/nw<24 and rect.height()*dh/nh<24
                and abs(position.x()-center_x)<3 and abs(position.y()-center_y)<3):return None
        corners=(rect.topLeft(),rect.topRight(),rect.bottomLeft(),rect.bottomRight())
        hits=[]
        for index,point in enumerate(corners):
            x=(self.width()-dw)/2+point.x()*dw/nw;y=self.pageTop(page)+point.y()*dh/nh
            distance=(position.x()-x)**2+(position.y()-y)**2
            if distance<=9**2:hits.append((distance,index))
        return min(hits)[1] if hits else None

    def _selectionResizeCursor(self, position):
        drag=self.selection_drag
        handle=drag['corner'] if drag and drag['kind']=='resize' else self._selectionHandleAt(position)
        if handle is None:return None
        return Qt.CursorShape.SizeFDiagCursor if handle in (0,3) else Qt.CursorShape.SizeBDiagCursor

    def _selectionPagePoint(self, page, position):
        nw,nh=self.editPageSize(page);dw,dh=self.draw_sizes[page]
        return ((position.x()-(self.width()-dw)/2)*nw/dw,
                (position.y()-self.pageTop(page))*nh/dh)

    def _boundedSelectionScale(self, bounds, anchor, requested):
        if not math.isfinite(requested) or requested<=0:raise ValueError('缩放比例应大于零')
        nw,nh=self.editPageSize(self.selection_page)
        limits=[20.]
        for edge,origin,limit in ((bounds.left(),anchor[0],nw),(bounds.right(),anchor[0],nw),
                                  (bounds.top(),anchor[1],nh),(bounds.bottom(),anchor[1],nh)):
            delta=edge-origin
            if delta>1e-10:limits.append(max(1.,(limit-origin)/delta))
            elif delta<-1e-10:limits.append(max(1.,-origin/delta))
        strokes=self.edits.state(self.selection_page)[0]
        widths=[s.width for i,s in enumerate(strokes) if i in self.selected_indices]
        if widths:limits.append(1000./max(widths))
        maximum=min(limits)
        minimum=min(maximum,max(.01,.001/min(widths)) if widths else .01)
        return max(minimum,min(maximum,requested))

    def _beginSelectionResize(self, position):
        corner=self._selectionHandleAt(position)
        if corner is None:return False
        bounds=self.selectionBounds();page=self.selection_page
        corners=(bounds.topLeft(),bounds.topRight(),bounds.bottomLeft(),bounds.bottomRight())
        anchor=corners[3-corner];moving=corners[corner]
        self.selection_drag=dict(kind='resize',page=page,corner=corner,bounds=bounds,
            start=self._selectionPagePoint(page,position),anchor=(anchor.x(),anchor.y()),
            vector=(moving.x()-anchor.x(),moving.y()-anchor.y()),scale=1.,preview=None)
        self.setFocus();self._syncBrushCursor();self.update()
        return True

    def _extendSelectionResize(self, position):
        drag=self.selection_drag
        if not drag or drag['kind']!='resize':return False
        point=self._selectionPagePoint(drag['page'],position)
        vx,vy=drag['vector'];dx=point[0]-drag['start'][0];dy=point[1]-drag['start'][1]
        requested=max(.000001,1.+(dx*vx+dy*vy)/max(1e-12,vx*vx+vy*vy))
        factor=self._boundedSelectionScale(drag['bounds'],drag['anchor'],requested)
        if abs(factor-1.)<1e-8:factor=1.
        if factor!=drag['scale']:
            drag['scale']=factor;drag['preview']=None;self.update()
        return True

    def _resizeSelectionPreview(self, page, strokes):
        drag=self.selection_drag
        if not drag or drag['kind']!='resize' or drag['page']!=page:return strokes
        if drag['preview'] is None:
            drag['preview']=[scale_stroke(s,drag['scale'],drag['anchor']) if i in self.selected_indices else s
                             for i,s in enumerate(strokes)]
        return drag['preview']

    def _commitSelectionScale(self, factor, anchor):
        changed=self.edits.change_selection(self.selection_page,self.selected_indices,scale=factor,anchor=anchor)
        if changed:
            if self.selection_region is not None:self.selection_region=scale_region(self.selection_region,factor,anchor)
            self._selection_highlight_cache=None
            self.editsChanged.emit()
        return changed

    def scaleSelectedInk(self, factor):
        if self.edit_tool!='select' or not self.selected_indices:return False
        self.finishGesture()
        bounds=self.selectionBounds();center=bounds.center();anchor=(center.x(),center.y())
        factor=self._boundedSelectionScale(bounds,anchor,float(factor))
        changed=self._commitSelectionScale(factor,anchor)
        self.selectionChanged.emit(len(self.selected_indices));self.update()
        return changed

    def _cancelSelectionResize(self):
        if getattr(self,'selection_drag',None) and self.selection_drag['kind']=='resize':
            self.selection_drag=None;self._selection_highlight_cache=None;self.update()

    def event(self, event):
        if (event.type() in (QEvent.Type.UngrabMouse,QEvent.Type.WindowDeactivate,QEvent.Type.Hide,QEvent.Type.EnabledChange)
                and hasattr(self,'selection_drag')
                and (event.type()!=QEvent.Type.EnabledChange or not self.isEnabled())):
            self._cancelSelectionResize()
        return super().event(event)

    def focusOutEvent(self, event):
        self._cancelSelectionResize()
        super().focusOutEvent(event)
