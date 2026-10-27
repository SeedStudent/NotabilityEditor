"""Append stable curves once; rebuild only the capture filter's mutable tail."""
import math
from PyQt6.QtCore import QPointF,Qt
from PyQt6.QtGui import QPainterPath,QColor,QPen
from editing.nv_edits import Stroke


class LiveStroke:
    def __init__(self):
        self.operation=None
        self.prefix=QPainterPath()
        self.next_index=1
        self.curves_built=0
        self.mode=None

    def _curve(self,path,points,index,width):
        previous,current,following=points[index-1:index+2]
        u=(current[0]-previous[0],current[1]-previous[1])
        v=(following[0]-current[0],following[1]-current[1])
        a,b=math.hypot(*u),math.hypot(*v)
        cosine=(u[0]*v[0]+u[1]*v[1])/(a*b) if a>1e-8 and b>1e-8 else 1.
        if cosine<.5 and min(a,b)>max(2.,width*.65):path.lineTo(*current)
        else:path.quadTo(QPointF(*current),QPointF((current[0]+following[0])/2,(current[1]+following[1])/2))
        self.curves_built+=1

    def path(self,op,smooth=True):
        points=op['points']
        mode=(smooth,bool(op.get('capture_smoothing')),op['width'])
        if self.operation is not op or self.mode!=mode or len(points)<self.next_index+1:
            self.operation=op;self.prefix=QPainterPath(QPointF(*points[0]));self.next_index=1
            self.mode=mode
        if smooth and not op.get('capture_smoothing'):
            return Stroke(tuple(points),op['color'],op['width']).render_path
        # Capture stabilization can still move points[-2]. Its neighbouring
        # segment is kept out of the permanent prefix until the next sample.
        if smooth:
            while self.next_index<=len(points)-4:
                self._curve(self.prefix,points,self.next_index,op['width']);self.next_index+=1
            result=QPainterPath(self.prefix)
            for index in range(self.next_index,len(points)-1):self._curve(result,points,index,op['width'])
        else:
            while self.next_index<len(points)-1:
                self.prefix.lineTo(*points[self.next_index]);self.next_index+=1
            result=QPainterPath(self.prefix)
        if len(points)>1:result.lineTo(*points[-1])
        return result

    def paint(self,painter,op,smooth=True):
        points=op['points']
        painter.save()
        try:
            painter.setRenderHint(painter.RenderHint.Antialiasing,True)
            painter.setOpacity(op.get('opacity',1.))
            painter.setPen(QPen(QColor(op['color']),op['width'],Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            if len(points)==1:painter.drawPoint(QPointF(*points[0]))
            else:painter.drawPath(self.path(op,smooth))
        finally:painter.restore()
