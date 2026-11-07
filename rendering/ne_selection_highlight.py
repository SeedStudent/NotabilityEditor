"""One bounded, disposable screen overlay; never used for notebook saving."""
import math
from PyQt6.QtCore import Qt,QRectF
from PyQt6.QtGui import QImage,QPainter,QColor


def _coverage_image(paths,width,height,bounds,color):
    """Tint a tool group's coverage once, regardless of native fragmentation."""
    image=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied);image.fill(0)
    p=QPainter(image)
    try:
        p.scale(width/bounds.width(),height/bounds.height());p.translate(-bounds.left(),-bounds.top())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('white'))
        for path in paths:p.drawPath(path)
        p.resetTransform()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        p.fillRect(image.rect(),color)
    finally:p.end()
    return image


def paint_highlight(canvas,painter,page,target,strokes,indices):
    if not indices:return
    transform=painter.combinedTransform()
    dpr=painter.device().devicePixelRatioF()
    sx=max(.01,math.hypot(transform.m11(),transform.m12())*dpr)
    sy=max(.01,math.hypot(transform.m21(),transform.m22())*dpr)
    width=max(1,round(target.width()*sx));height=max(1,round(target.height()*sy))
    nw,nh=canvas.editPageSize(page)
    core=canvas.edits.core if hasattr(canvas.edits,'core') else canvas.edits
    selected=tuple(strokes[i] for i in sorted(indices) if 0<=i<len(strokes))
    if not selected:return
    # Preview geometry can change without a history commit (corner resizing).
    key=(page,width,height,nw,nh,core.token,core.cursor,canvas.ink_smoothing,selected)
    cached=canvas._selection_highlight_cache
    if cached is None or cached[0]!=key:
        paths=tuple(s.selection_outline if canvas.ink_smoothing else s.linear_selection_outline for s in selected)
        bounds=QRectF()
        for path in paths:bounds=bounds.united(path.boundingRect())
        # Keep the full selected geometry, including caps beyond a page edge,
        # so dragging it back onto the page cannot reveal a clipped highlight.
        # A tight mask also avoids allocating an entire page for a small word.
        bounds=bounds.adjusted(-nw/width,-nh/height,nw/width,nh/height)
        width=max(1,math.ceil(bounds.width()*width/nw))
        height=max(1,math.ceil(bounds.height()*height/nh))
        factor=min(1.,math.sqrt(canvas.MAX_RENDER_PIXELS/(width*height)))
        width=max(1,int(width*factor));height=max(1,int(height*factor))
        markers=tuple(path for stroke,path in zip(selected,paths) if stroke.is_highlighter)
        ink=tuple(path for stroke,path in zip(selected,paths) if not stroke.is_highlighter)
        # The broad highlighter gets a light wash; selected handwriting is
        # tinted afterwards so its thin lines remain legible over that wash.
        # Each group still uses a flat coverage mask, never per-fragment rims.
        image=_coverage_image(markers,width,height,bounds,QColor(82,169,255,64)) if markers else None
        if ink:
            foreground=_coverage_image(ink,width,height,bounds,QColor(37,99,235,176))
            if image is None:image=foreground
            else:
                p=QPainter(image)
                try:p.drawImage(0,0,foreground)
                finally:p.end()
        canvas._selection_highlight_cache=(key,image,bounds)
    _,image,bounds=canvas._selection_highlight_cache
    area=QRectF(target.left()+bounds.left()*target.width()/nw,target.top()+bounds.top()*target.height()/nh,
                bounds.width()*target.width()/nw,bounds.height()*target.height()/nh)
    painter.drawImage(area,image)
