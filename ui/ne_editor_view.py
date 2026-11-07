"""Presentation-only fullscreen and outside-paper navigation."""
from PyQt6.QtCore import QObject, QEvent, QPoint, QPointF, Qt, QTimer
from PyQt6 import sip
from PyQt6.QtGui import QAction, QCursor
from PyQt6.QtWidgets import QApplication


class EditorView(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.drag = None
        self.saved = None
        self.application_active = True
        self.cursor_active = True
        self._layout_serial = 0
        self._view_anchor = None
        self.action = QAction('全屏编辑', owner)
        from ui.ne_toolbar import tool_icon
        self.action.setIcon(tool_icon('expand'))
        self.action.setToolTip('全屏编辑')
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle)
        owner.fullscreen_action = self.action
        owner.addAction(self.action)
        self.fullscreen_button = owner.editor_panel.tool_button(
            owner.editor_panel.tool_row.commands_layout, self.action, icon_only=True)
        owner.editor_panel.tool_row.sync_layout()
        owner.menus['视图'].addAction(self.action)
        from ui.ne_fullscreen_toolbar import FullscreenToolbar
        self.fullscreen_toolbar = FullscreenToolbar(self)
        self.bar = self.fullscreen_toolbar.bar
        self.bar.hide()
        owner.scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents)
        owner.scroll.viewport().setMouseTracking(True)
        self.cursor_refresh = QTimer(self)
        self.cursor_refresh.setSingleShot(True)
        self.cursor_refresh.timeout.connect(self.sync_cursor)
        for scrollbar in (owner.scroll.horizontalScrollBar(), owner.scroll.verticalScrollBar()):
            scrollbar.valueChanged.connect(self.schedule_cursor_refresh)
        self.sync_cursor()
        QApplication.instance().installEventFilter(self)

    def busy_gesture(self):
        c = self.owner.canvas
        return bool(c and (getattr(getattr(c, 'edits', None), 'pending', None) or getattr(c, 'selection_drag', None)
            or getattr(c, '_continuous_draw', None) is not None or getattr(c, '_image_drag', None) or getattr(c, '_image_resize_drag', None)
            or getattr(c, '_reading_pan', None) is not None)) or self.drag is not None

    def capture_anchor(self):
        o=self.owner
        if o.canvas is None:return
        if self._view_anchor and self._view_anchor[0] is o.canvas:return
        viewport=o.scroll.viewport()
        self._view_anchor=(o.canvas,o.canvas.mapFrom(viewport,viewport.rect().center()),o.zoom)

    def restore_anchor(self):
        self._layout_serial+=1;serial=self._layout_serial;anchor=self._view_anchor
        def restore():
            if sip.isdeleted(self) or sip.isdeleted(self.owner):return
            if serial!=self._layout_serial:return
            self._view_anchor=None
            o=self.owner
            if anchor is None or o.canvas is not anchor[0]:return
            canvas,point,zoom=anchor;viewport=o.scroll.viewport()
            if sip.isdeleted(canvas):return
            if o.fit_width:o.fit()
            ratio=o.zoom/zoom
            target=canvas.mapTo(viewport,QPoint(round(point.x()*ratio),round(point.y()*ratio)))
            delta=target-viewport.rect().center()
            o.scroll.horizontalScrollBar().setValue(o.scroll.horizontalScrollBar().value()+delta.x())
            o.scroll.verticalScrollBar().setValue(o.scroll.verticalScrollBar().value()+delta.y())
            self.schedule_cursor_refresh()
        QTimer.singleShot(80,restore)

    def toggle(self, checked=False):
        o = self.owner
        if o.canvas is None and self.saved is None:
            self.action.setChecked(False)
            return
        if self.busy_gesture():
            self.action.setChecked(self.saved is not None)
            o.statusBar().showMessage('请结束当前手势后切换全屏', 2500)
            return
        self.fullscreen_toolbar.cancel_drag()
        entering = self.saved is None
        self.capture_anchor()
        if entering:
            self.saved = (o.saveGeometry(), o.windowState(), not o.page_sidebar.isHidden())
            self._normal_visibility=(not o.menuBar().isHidden(),not o.read_toolbar.isHidden(),not o.edit_toolbar.isHidden(),not o.statusBar().isHidden())
            o.menuBar().hide();o.read_toolbar.hide();o.edit_toolbar.hide();o.page_sidebar.hide();o.statusBar().hide()
            self.fullscreen_toolbar.enter();o.showFullScreen()
        else:
            geometry, state, sidebar = self.saved
            self.fullscreen_toolbar.leave()
            self.saved = None
            o.setWindowState(state);o.restoreGeometry(geometry)
            for widget,visible in zip((o.menuBar(),o.read_toolbar,o.edit_toolbar,o.statusBar()),self._normal_visibility):widget.setVisible(visible)
            o.page_sidebar.setVisible(sidebar)
        self.action.setChecked(entering)
        self.action.setText('退出全屏' if entering else '全屏编辑')
        from ui.ne_toolbar import tool_icon
        self.action.setIcon(tool_icon('collapse' if entering else 'expand'))
        self.action.setToolTip(self.action.text())
        self.fullscreen_button.setAccessibleName(self.action.text())
        self.restore_anchor()

    def leave(self):
        if self.saved is not None:self.toggle()

    def cancel_drag(self):
        drag = self.drag
        self.drag = None
        if drag:
            drag['canvas']._navigation_drag = False
            # Release can deliver enter/leave events synchronously. They must see
            # the completed gesture, and the canvas must keep its own cursor.
            if drag['kind'] == 'mouse':drag['receiver'].releaseMouse()
            self.sync_cursor()

    def schedule_cursor_refresh(self, *args):
        if self.application_active and not self.cursor_refresh.isActive():
            self.cursor_refresh.start(0)

    def owns_window(self, widget):
        # QWidget.isAncestorOf stops at top-level window boundaries.
        while widget is not None:
            if widget is self.owner:return True
            widget = widget.parentWidget()
        return False

    def sync_cursor(self):
        """Re-evaluate the visible canvas after a grab or scroll moves the paper."""
        # Closing a modal new-note/progress window does not always deliver a
        # matching WindowActivate to its owner. Reconcile with Qt's current
        # active window instead of keeping that old deactivation indefinitely.
        active = QApplication.activeWindow()
        closed_modal = (active is not None and not active.isVisible() and self.owns_window(active))
        self.cursor_active = self.application_active and (self.owner.isActiveWindow() or closed_modal)
        if self.drag is not None:
            self.drag['receiver'].setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        c = self.owner.canvas
        viewport = self.owner.scroll.viewport()
        viewport.setCursor(Qt.CursorShape.OpenHandCursor if c else Qt.CursorShape.ArrowCursor)
        if c is None or not hasattr(c, '_moveHover'):return
        point = QCursor.pos()
        local = c.mapFromGlobal(point)
        visible = (self.cursor_active and not QApplication.activePopupWidget() and not QApplication.activeModalWidget()
                   and c.rect().contains(local) and viewport.rect().contains(viewport.mapFromGlobal(point))
                   and QApplication.widgetAt(point) is c)
        c._moveHover(QPointF(local) if visible else None)

    def outside_paper(self, point):
        c = self.owner.canvas
        local = c.mapFromGlobal(point.toPoint())
        if hasattr(c, 'pointOnPage'):return c.pointOnPage(QPointF(local)) is None
        return not c.rect().contains(local)

    def eventFilter(self, obj, event):
        o = self.owner
        t = event.type()
        toolbar=self.fullscreen_toolbar
        if t==QEvent.Type.KeyPress and event.key()==Qt.Key.Key_Escape and toolbar.cancel_drag():return True
        if t==QEvent.Type.UngrabMouse and obj is toolbar.grip:toolbar.cancel_drag()
        if obj is o and t==QEvent.Type.Resize:
            toolbar.cancel_drag();toolbar.popup.hide()
        if t == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self.drag:
            self.cancel_drag();return True
        if t == QEvent.Type.ApplicationDeactivate or (obj is o and t == QEvent.Type.WindowDeactivate):
            if t == QEvent.Type.ApplicationDeactivate:self.application_active = False
            self.cursor_active = False
            self.cursor_refresh.stop()
            toolbar.cancel_drag()
            self.cancel_drag()
            if o.canvas is not None and hasattr(o.canvas, '_moveHover'):o.canvas._moveHover(None)
        if t == QEvent.Type.ApplicationActivate or (obj is o and t == QEvent.Type.WindowActivate):
            if t == QEvent.Type.ApplicationActivate:self.application_active = True
            self.cursor_active = True
            self.schedule_cursor_refresh()
        # Also recover a stationary pointer when an owned modal/popup closes.
        # Queuing lets Qt finish visibility and activation changes first.
        if (t in (QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Close)
                and obj.isWidgetType() and obj.isWindow()):
            if self.owns_window(obj):self.schedule_cursor_refresh()
        if (t == QEvent.Type.UngrabMouse and self.drag is not None
                and self.drag['kind'] == 'mouse' and obj is self.drag['receiver']):
            self.cancel_drag()
        if t == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self.saved:
            if (not QApplication.activePopupWidget() and not QApplication.activeModalWidget()
                and not self.busy_gesture() and not getattr(o.canvas, 'selected_indices', ())
                and not getattr(o.canvas, 'selected_image', None)):
                self.leave();return True
        c = o.canvas
        if c is None:return False
        viewport = o.scroll.viewport()
        if obj in (c, viewport):
            if t in (QEvent.Type.Resize, QEvent.Type.Move, QEvent.Type.Show):
                toolbar.sync_commands()
                self.schedule_cursor_refresh()
            if t in (QEvent.Type.Enter, QEvent.Type.Leave):
                if self.drag is not None:
                    self.drag['receiver'].setCursor(Qt.CursorShape.ClosedHandCursor)
                    if obj is c:return True
                if obj is viewport:
                    if self.drag is None:viewport.setCursor(Qt.CursorShape.OpenHandCursor)
                self.schedule_cursor_refresh()
        mouse = t in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease)
        tablet = t in (QEvent.Type.TabletPress, QEvent.Type.TabletMove, QEvent.Type.TabletRelease)
        touch = t in (QEvent.Type.TouchBegin, QEvent.Type.TouchUpdate, QEvent.Type.TouchEnd, QEvent.Type.TouchCancel)
        if not (mouse or tablet or touch):return False
        if touch:
            points = event.points()
            if t == QEvent.Type.TouchCancel and self.drag and self.drag['kind'] == 'touch':
                self.cancel_drag();event.accept();return True
            if not points:return False
            point = points[0].globalPosition()
        else:point = event.globalPosition()
        start = t in (QEvent.Type.MouseButtonPress, QEvent.Type.TabletPress, QEvent.Type.TouchBegin)
        end = t in (QEvent.Type.MouseButtonRelease, QEvent.Type.TabletRelease, QEvent.Type.TouchEnd, QEvent.Type.TouchCancel)
        kind = 'mouse' if mouse else 'tablet' if tablet else 'touch'
        if self.drag:
            if kind != self.drag['kind']:return False
            if mouse and t == QEvent.Type.MouseMove and not event.buttons() & Qt.MouseButton.LeftButton:
                self.cancel_drag();return False
            dx = point.x()-self.drag['x'];dy = point.y()-self.drag['y']
            o.scroll.horizontalScrollBar().setValue(round(self.drag['h']-dx))
            o.scroll.verticalScrollBar().setValue(round(self.drag['v']-dy))
            if end:self.cancel_drag()
            event.accept();return True
        if obj not in (c, viewport):return False
        if not start:return False
        if mouse and event.button() != Qt.MouseButton.LeftButton:return False
        if not self.outside_paper(point):return False
        if self.busy_gesture():return False
        if hasattr(c, '_cancelReadingPan'):c._cancelReadingPan()
        if hasattr(c, '_moveHover'):c._moveHover(None)
        c._navigation_drag = True
        self.drag = dict(x=point.x(), y=point.y(), h=o.scroll.horizontalScrollBar().value(),
                         v=o.scroll.verticalScrollBar().value(), receiver=obj, kind=kind)
        self.drag['canvas'] = c
        obj.setCursor(Qt.CursorShape.ClosedHandCursor)
        if mouse:obj.grabMouse()
        event.accept();return True
