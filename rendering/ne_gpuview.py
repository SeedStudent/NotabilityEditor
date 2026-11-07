"""Bounded, retained OpenGL viewport with coalesced damage and CPU recovery."""
import math
from time import perf_counter
from PyQt6 import sip
from PyQt6.QtCore import QObject,QEvent,QPoint,QRect,Qt,QTimer,pyqtSignal
from PyQt6.QtGui import QPainter,QSurfaceFormat,QRegion
from PyQt6.QtWidgets import QApplication
from infrastructure.ne_diagnostics import exception as diagnostic_exception,stage as diagnostic_stage


def hardware_renderer(name):
    name=str(name or '').lower()
    return bool(name) and not any(s in name for s in (
        'llvmpipe','softpipe','swiftshader','software','gdi generic',
        'microsoft basic render','mesa offscreen'))


def platform_supported():
    return QApplication.platformName().lower() not in ('offscreen','minimal','vnc')


class GpuViewport(QObject):
    changed=pyqtSignal(bool,str)
    MAX_PIXELS=16_000_000
    FRAME_INTERVAL_MS=16
    STALL_MS=750
    SLOW_FRAME_SECONDS=.1

    def __init__(self,scroll,enabled=True,parent=None):
        super().__init__(parent)
        self.scroll=scroll;self.enabled=bool(enabled);self.canvas=None;self.surface=None
        self.active=False;self.description='软件绘制';self.failed=False
        self._generation=0
        self._dirty=None;self._frame_key=None
        self._paint_serial=0;self._request_serial=0;self._awaiting_frame=False
        self._frames=0;self._slow_frames=0
        self._frame_timer=QTimer(self);self._frame_timer.setSingleShot(True)
        self._frame_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._frame_timer.setInterval(self.FRAME_INTERVAL_MS)
        self._frame_timer.timeout.connect(self._flush_update)
        self._stall_timer=QTimer(self);self._stall_timer.setSingleShot(True)
        self._stall_timer.setInterval(self.STALL_MS)
        self._stall_timer.timeout.connect(self._stalled)
        scroll.viewport().installEventFilter(self)
        scroll.verticalScrollBar().valueChanged.connect(self.refresh)
        scroll.horizontalScrollBar().valueChanged.connect(self.refresh)

    def attach(self,canvas):
        self.detach();self.canvas=canvas
        if not hasattr(canvas,'paintVisible'):return
        canvas._gpu_view=self;canvas.installEventFilter(self)
        if self.enabled:self._create()

    def detach(self):
        self._generation+=1;self.active=False
        self._frame_timer.stop();self._stall_timer.stop();self._awaiting_frame=False
        self._dirty=None;self._frame_key=None;self._frames=0;self._slow_frames=0
        if self.canvas is not None and not sip.isdeleted(self.canvas):
            self.canvas.removeEventFilter(self);self.canvas._gpu_view=None;self.canvas.update()
        self.canvas=None
        surface=self.surface;self.surface=None
        if surface is not None and not sip.isdeleted(surface):surface.hide();surface.deleteLater()
        self.description='软件绘制'

    def setEnabled(self,enabled):
        self.enabled=bool(enabled);canvas=self.canvas
        if self.enabled:self.failed=False
        if canvas is not None:self.attach(canvas)

    def _within_budget(self):
        viewport=self.scroll.viewport();dpr=viewport.devicePixelRatioF()
        return math.ceil(viewport.width()*dpr)*math.ceil(viewport.height()*dpr)<=self.MAX_PIXELS

    def _current(self,surface,generation):
        return generation==self._generation and self.surface is surface and not sip.isdeleted(surface)

    def _create(self):
        if self.failed or not platform_supported() or not self._within_budget():return
        try:
            from PyQt6.QtOpenGLWidgets import QOpenGLWidget
            owner=self;generation=self._generation
            class Surface(QOpenGLWidget):
                def initializeGL(self):
                    if not owner._current(self,generation):return
                    try:
                        from PyQt6.QtOpenGL import QOpenGLVersionProfile,QOpenGLVersionFunctionsFactory
                        context=self.context()
                        if context is None or not context.isValid():raise RuntimeError('OpenGL 上下文不可用')
                        profile=QOpenGLVersionProfile();profile.setVersion(2,0)
                        self._functions=QOpenGLVersionFunctionsFactory.get(profile,context)
                        if self._functions is None:raise RuntimeError('OpenGL 2.0 绘制接口不可用')
                        self._functions.initializeOpenGLFunctions()
                        renderer=self._functions.glGetString(0x1F01)
                        if isinstance(renderer,bytes):renderer=renderer.decode('utf-8','replace')
                        renderer=str(renderer or '')
                        if not hardware_renderer(renderer):raise RuntimeError('当前驱动仅提供软件 OpenGL')
                        self._context=context
                        context.aboutToBeDestroyed.connect(lambda:owner._context_lost(self,generation))
                        owner._frame_key=None;owner._dirty=None
                        owner.active=True;owner.description=renderer
                        diagnostic_stage('GPU viewport: '+renderer)
                        owner.changed.emit(True,renderer);owner.refresh()
                    except Exception as exc:owner._fail(str(exc))

                def resizeGL(self,width,height):
                    if owner._current(self,generation):
                        owner._frame_key=None;owner.refresh()

                def paintGL(self):
                    if not owner._current(self,generation) or not owner.active:return
                    canvas=owner.canvas
                    if canvas is None or sip.isdeleted(canvas):return
                    painter=None;started=perf_counter()
                    try:
                        if not self.isValid() or not owner._within_budget():raise RuntimeError('GPU 绘制上下文或窗口尺寸已失效')
                        origin=canvas.mapFrom(owner.scroll.viewport(),QPoint(0,0))
                        damage=owner._take_damage(self,origin)
                        if damage.isEmpty():return
                        error=self._functions.glGetError()
                        if error in (0x0505,0x0507):raise RuntimeError(f'OpenGL 状态异常 (0x{error:04x})')
                        painter=QPainter(self)
                        if not painter.isActive():raise RuntimeError('GPU 绘制上下文已失效')
                        painter.setClipRegion(damage)
                        painter.translate(-origin.x(),-origin.y())
                        canvas.paintVisible(painter,damage.boundingRect().translated(origin),self.devicePixelRatioF(),strict=True)
                        painter.end();painter=None
                        error=self._functions.glGetError()
                        if error:raise RuntimeError(f'OpenGL 绘制失败 (0x{error:04x})')
                        owner._paint_serial+=1
                        owner._record_frame(perf_counter()-started)
                    except Exception as exc:
                        diagnostic_exception('GPU viewport paint',exc);owner._fail(str(exc))
                    finally:
                        if painter is not None and painter.isActive():painter.end()
            surface=Surface(self.scroll.viewport())
            fmt=QSurfaceFormat();fmt.setVersion(2,0);fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.NoProfile)
            fmt.setStencilBufferSize(8);fmt.setDepthBufferSize(0)
            # QPainter antialiases ink without a multisampled full-screen FBO.
            fmt.setSamples(0);fmt.setSwapInterval(1);surface.setFormat(fmt)
            surface.setUpdateBehavior(QOpenGLWidget.UpdateBehavior.PartialUpdate)
            surface.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents,True)
            surface.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            surface.frameSwapped.connect(lambda:self._presented(surface,generation))
            self.surface=surface;surface.setGeometry(self.scroll.viewport().rect());surface.show();surface.raise_()
            QTimer.singleShot(350,lambda:self._verify(surface,generation))
        except Exception as exc:self._fail(str(exc))

    def _take_damage(self,surface,origin):
        key=(surface.defaultFramebufferObject(),surface.width(),surface.height(),surface.devicePixelRatioF(),origin.x(),origin.y())
        if key!=self._frame_key:
            self._frame_key=key;self._dirty=None;self._frames=0;self._slow_frames=0
        damage=QRegion(surface.rect()) if self._dirty is None else self._dirty.intersected(surface.rect())
        self._dirty=QRegion()
        return damage

    def _context_lost(self,surface,generation):
        if not self._current(surface,generation) or self.failed:return
        self.active=False;self._frame_key=None;self._dirty=None
        self._frame_timer.stop();self._stall_timer.stop();self._awaiting_frame=False
        # Fullscreen can recreate a context normally; allow initializeGL to
        # recover, but never keep an inert overlay indefinitely.
        QTimer.singleShot(350,lambda:self._verify(surface,generation))

    def _verify(self,surface,generation):
        if not self._current(surface,generation) or self.failed:return
        if not surface.isValid() or not self.active:self._fail('OpenGL 上下文未恢复')

    def _record_frame(self,elapsed):
        self._frames+=1
        self._slow_frames=self._slow_frames+1 if self._frames>2 and elapsed>self.SLOW_FRAME_SECONDS else 0
        if self._slow_frames>=3:self._fail('GPU 连续绘制耗时过长，已切换软件绘制')

    def _presented(self,surface,generation):
        if not self._current(surface,generation) or not self.active:return
        # Composing an old texture is not proof that a requested new frame
        # was painted. Only a newer successful paint clears the watchdog.
        if self._awaiting_frame and self._paint_serial>self._request_serial:
            self._awaiting_frame=False;self._stall_timer.stop()

    def _stalled(self):
        surface=self.surface
        if not self.active or not self._awaiting_frame or surface is None:return
        if not surface.isVisible() or surface.window().isMinimized():
            self._awaiting_frame=False;return
        self._fail('GPU 画面未及时刷新，已切换软件绘制')

    def _fail(self,reason):
        if self.failed:return
        from infrastructure.ne_diagnostics import warning
        warning('GPU fallback: '+reason)
        self.active=False;self.failed=True;self.description='软件绘制：'+reason
        self._frame_timer.stop();self._stall_timer.stop();self._awaiting_frame=False
        generation=self._generation
        QTimer.singleShot(0,lambda:self._fallback(generation))

    def _fallback(self,generation):
        if generation!=self._generation:return
        surface=self.surface;self.surface=None
        if surface is not None and not sip.isdeleted(surface):surface.hide();surface.deleteLater()
        if self.canvas is not None and not sip.isdeleted(self.canvas):self.canvas.update()
        self.changed.emit(False,self.description)

    def refresh(self,*args):
        if self.surface is None or not self.active or self.failed:return
        # Scrollbars carry an int; canvas.update carries rects/regions in canvas
        # coordinates. A full update dominates all local damage in that frame.
        damage=(QRegion(args[0]) if len(args)==1 and isinstance(args[0],(QRect,QRegion)) else
                QRegion(QRect(*args)) if len(args)==4 and all(isinstance(a,int) for a in args) else None)
        if damage is None:self._dirty=None
        elif self._dirty is not None and self.canvas is not None:
            offset=self.canvas.mapTo(self.scroll.viewport(),QPoint(0,0))
            damage=damage.translated(offset).intersected(self.scroll.viewport().rect())
            if damage.isEmpty():return
            self._dirty=self._dirty.united(damage)
            if self._dirty.rectCount()>64:self._dirty=QRegion(self._dirty.boundingRect())
        if not self._frame_timer.isActive():self._frame_timer.start()

    def _flush_update(self):
        surface=self.surface
        if surface is None or not self.active or self.failed:return
        if not surface.isValid():self._fail('OpenGL 上下文已失效');return
        if not self._within_budget():self._fail('窗口绘制面积超过加速上限');return
        if not surface.isVisible():return
        if self._dirty is not None and self._dirty.isEmpty():return
        if not self._awaiting_frame:
            self._awaiting_frame=True;self._request_serial=self._paint_serial;self._stall_timer.start()
        surface.update()

    def eventFilter(self,obj,event):
        if event.type() in (QEvent.Type.Resize,QEvent.Type.Move,QEvent.Type.Show):
            surface=self.surface
            if surface is not None and not self.failed:
                if not self._within_budget():self._fail('窗口绘制面积超过加速上限')
                else:
                    geometry=self.scroll.viewport().rect()
                    if surface.geometry()!=geometry:surface.setGeometry(geometry)
                    self.refresh()
        return False
