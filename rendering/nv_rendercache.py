"""Bounded screen-only stable layers. Vector export keeps its original path."""
from collections import OrderedDict
import math
from PyQt6.QtCore import QRectF,QSize
from PyQt6.QtGui import QImage,QPainter
from rendering.nv_livestroke import LiveStroke
from rendering.nv_mixed_layers import scene,paint_native_scene,paint_content,NEW_INK_LAYER
from images.nv_imagedrag import ImageDragLayers


class ContentCache:
    BUDGET=96*1024*1024

    def __init__(self):
        self.entries=OrderedDict();self.bytes=0;self.live=LiveStroke()
        self.hits=0;self.misses=0
        self.image_drag=ImageDragLayers()

    def clear(self):
        self.entries.clear();self.bytes=0
        self.image_drag.clear()

    def invalidate_pages(self,pages):
        for key in list(self.entries):
            if key[0] in pages:
                old=self.entries.pop(key);self.bytes-=sum(i.sizeInBytes() for i in old)

    def paint(self,c,painter,page,target,dpr=1.):
        op=c.edits.pending
        active=op and op['page']==page
        image_gesture=getattr(c,'_image_drag',None) or getattr(c,'_image_resize_drag',None)
        if image_gesture and self.image_drag.paint(c,painter,page,target,dpr,self.BUDGET):
            while self.entries and self.bytes+self.image_drag.bytes>self.BUDGET:
                _,old=self.entries.popitem(last=False);self.bytes-=sum(i.sizeInBytes() for i in old)
            return
        # Erasure and object moves have mutable stable contents. They retain
        # the shared vector path rather than displaying an obsolete bitmap.
        if (active and op['kind']!='draw') or c.selectionMovingOnPage(page):
            paint_content(c,painter,page,target,include_ink=c.show_ink);return
        # Pens and highlighters share the same top insertion boundary. A
        # behind-content highlighter cache would cover its live path with images.
        boundary=(NEW_INK_LAYER+1,0)
        width,height=max(1,round(target.width()*dpr)),max(1,round(target.height()*dpr))
        factor=min(1.,math.sqrt(c.MAX_RENDER_PIXELS/(width*height)))
        size=QSize(max(1,round(width*factor)),max(1,round(height*factor)))
        core=c.edits.core if hasattr(c.edits,'core') else c.edits
        key=(page,size.width(),size.height(),core.token,core.cursor,c.show_ink,c.ink_smoothing,boundary)
        pair=self.entries.get(key)
        if pair is None:
            self.misses+=1
            entries=scene(c,page,include_ink=c.show_ink,static=True)
            back=[e for e in entries if (e[0],e[1])<=boundary]
            front=[e for e in entries if (e[0],e[1])>boundary]
            target_image=QRectF(0,0,size.width(),size.height())
            pair=[]
            for before,records in ((True,back),(False,front)):
                image=QImage(size,QImage.Format.Format_ARGB32_Premultiplied);image.fill(0)
                p=QPainter(image)
                try:
                    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform,True)
                    if before:c.paintInsertedImages(p,page,target_image,front=False)
                    paint_native_scene(c,p,page,target_image,entries=records)
                    if not before:c.paintInsertedImages(p,page,target_image,front=True)
                finally:p.end()
                pair.append(image)
            cost=sum(i.sizeInBytes() for i in pair)
            if cost+self.image_drag.bytes<=self.BUDGET:
                self.entries[key]=pair;self.bytes+=cost
                while self.bytes+self.image_drag.bytes>self.BUDGET:
                    _,old=self.entries.popitem(last=False);self.bytes-=sum(i.sizeInBytes() for i in old)
        else:self.hits+=1
        if key in self.entries:self.entries.move_to_end(key)
        painter.drawImage(target,pair[0])
        if active and c.show_ink:
            nw,nh=c.editPageSize(page)
            painter.save()
            try:
                painter.setClipRect(target)
                painter.translate(target.x(),target.y());painter.scale(target.width()/nw,target.height()/nh)
                # PageEdits.pending is a display-page wrapper created on each
                # access; the core operation retains identity across samples.
                self.live.paint(painter,core.pending,c.ink_smoothing)
            finally:painter.restore()
        painter.drawImage(target,pair[1])
