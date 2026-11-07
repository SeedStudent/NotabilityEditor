"""Large fullscreen controls with reversible, previewed edge docking."""
from PyQt6.QtCore import Qt,QPoint,QRect,QRectF,QSize
from PyQt6.QtGui import QAction,QActionGroup,QColor,QFont,QPainter,QPen,QPixmap,QIcon
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtCore import QByteArray
from PyQt6 import sip
from PyQt6.QtWidgets import (QApplication,QWidget,QFrame,QToolBar,QToolButton,QLabel,
    QBoxLayout,QHBoxLayout,QVBoxLayout,QGridLayout,QScrollArea,QSizePolicy)
from ui.ne_style import style_menu
from PyQt6.QtWidgets import QMenu


# Separate silhouettes and accent colours remain recognizable at a glance.
TOOL_ART={
    'draw':('#2563eb','<path d="m5 18 1-5L17 2l5 5-11 11-6 1Zm2-6 5 5M15 4l5 5M3 22h15"/>'),
    'highlight':('#a16207','<path d="m5 14 8-12 8 5-8 12H7l-2-5Zm2-3 8 5M12 4l7 5"/><path d="M3 22h18" stroke="#eab308" stroke-width="3.5"/>'),
    'tape':('#c2410c','<rect x="2" y="5" width="20" height="14" rx="3"/><path d="m6 6 3 3-3 3 3 3-3 3M16 6l3 3-3 3 3 3-3 3"/>'),
    'shape':('#7c3aed','<rect x="2" y="2" width="11" height="11" rx="2"/><circle cx="16" cy="16" r="6"/>'),
    'erase':('#be185d','<path d="m3 13 9-10a2 2 0 0 1 3 0l6 6a2 2 0 0 1 0 3l-8 9H9l-6-5a2 2 0 0 1 0-3ZM7 9l10 9M13 21h9"/>'),
    'select':('#0369a1','<path d="M9 3H3v6M15 3h6v6M3 15v6h6" stroke-dasharray="2 2"/><path d="m12 11 9 4-4 2-2 4-3-10Z"/>'),
    'image':('#047857','<rect x="2" y="3" width="20" height="18" rx="3"/><circle cx="8" cy="8" r="2"/><path d="m3 18 6-6 4 4 3-5 5 7"/>'),
    'read':('#475569','<path d="M8 12V5a2 2 0 0 1 4 0v7-8a2 2 0 0 1 4 0v8-6a2 2 0 0 1 4 0v9c0 5-3 7-7 7-3 0-5-2-7-5l-3-4a2 2 0 0 1 3-3l2 2Z"/>'),
    'options':('#475569','<path d="M3 6h18M3 12h18M3 18h18"/><circle cx="8" cy="6" r="2" fill="white"/><circle cx="16" cy="12" r="2" fill="white"/><circle cx="10" cy="18" r="2" fill="white"/>'),
    'position':('#475569','<rect x="2" y="3" width="20" height="18" rx="3"/><path d="M3 16h18M8 4v12"/>'),
    'grip':('#64748b','<g fill="currentColor" stroke="none"><circle cx="8" cy="5" r="1.7"/><circle cx="16" cy="5" r="1.7"/><circle cx="8" cy="12" r="1.7"/><circle cx="16" cy="12" r="1.7"/><circle cx="8" cy="19" r="1.7"/><circle cx="16" cy="19" r="1.7"/></g>'),
}


def fullscreen_icon(key):
    from ui.ne_toolbar import ICONS
    color,art=TOOL_ART.get(key,('#475569',ICONS.get(key,'')))
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" color="{color}"><g fill="none" stroke="{color}" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">{art}</g></svg>'
    pixmap=QPixmap(96,96);pixmap.fill(Qt.GlobalColor.transparent)
    painter=QPainter(pixmap)
    try:QSvgRenderer(QByteArray(svg.encode())).render(painter)
    finally:painter.end()
    return QIcon(pixmap)


class FullscreenButton(QToolButton):
    def __init__(self,key,label='',action=None,parent=None):
        super().__init__(parent)
        self.key=key;self.label=label;self.art=fullscreen_icon(key);self.compact=False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True);self.setFixedSize(64,60) if label else self.setFixedSize(44,44)
        if action is not None:self.setDefaultAction(action)
        self.setAccessibleName(action.text() if action else label)
        self.setIcon(self.art)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect=QRectF(self.rect()).adjusted(2,2,-2,-2)
        if not self.isEnabled():p.setOpacity(.35)
        checked=self.isChecked()
        p.setPen(QPen(QColor('#2563eb') if checked else QColor('#cbd5e1') if self.hasFocus() else Qt.GlobalColor.transparent,1.5))
        p.setBrush(QColor('#dbeafe') if self.isDown() else QColor('#e8f0ff') if checked else QColor('#f1f5f9') if self.underMouse() else QColor('#ffffff'))
        p.drawRoundedRect(rect,11,11)
        size=24 if self.compact else 28
        icon=QRect((self.width()-size)//2,(4 if self.compact else 7) if self.label else (self.height()-size)//2,size,size)
        self.art.paint(p,icon)
        if self.label:
            font=QFont('Microsoft YaHei UI');font.setPixelSize(10 if self.compact else 12);font.setWeight(QFont.Weight.DemiBold if checked else QFont.Weight.Normal)
            p.setFont(font);p.setPen(QColor('#1d4ed8') if checked else QColor('#334155'))
            p.drawText(QRect(0,29 if self.compact else 36,self.width(),16 if self.compact else 20),Qt.AlignmentFlag.AlignCenter,self.label)
        if checked:
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#2563eb'));p.drawEllipse(QPoint(self.width()-9,9),3,3)


class DockPreview(QWidget):
    def __init__(self,parent):
        super().__init__(parent);self.caption=''
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(37,99,235,25));p.setPen(QPen(QColor('#2563eb'),2,Qt.PenStyle.DashLine))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(3,3,-3,-3),12,12)
        p.setPen(QColor('#1d4ed8'));font=QFont('Microsoft YaHei UI');font.setPixelSize(12);p.setFont(font)
        p.drawText(self.rect().adjusted(8,8,-8,-8),Qt.AlignmentFlag.AlignCenter|Qt.TextFlag.TextWordWrap,self.caption)


class DragGrip(FullscreenButton):
    def __init__(self,controller,parent=None):
        super().__init__('grip',parent=parent);self.controller=controller
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip('拖动到顶部、底部、左侧或右侧；虚线预览，松开确定，Esc 取消')
        self.setAccessibleName('拖动全屏工具栏')

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.controller.press(event.globalPosition().toPoint());event.accept()
        else:super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.controller.move(event.globalPosition().toPoint());event.accept()
        else:super().mouseMoveEvent(event)

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.controller.release(event.globalPosition().toPoint());event.accept()
        else:super().mouseReleaseEvent(event)


class ToolbarContents(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.side=False

    def sizeHint(self):return QSize(64,0) if self.side else QSize(0,76)
    def minimumSizeHint(self):return self.sizeHint()


class FullscreenToolbar:
    POSITIONS={'bottom':('底部',Qt.ToolBarArea.BottomToolBarArea),
               'top':('顶部',Qt.ToolBarArea.TopToolBarArea),
               'left':('左侧',Qt.ToolBarArea.LeftToolBarArea),
               'right':('右侧',Qt.ToolBarArea.RightToolBarArea)}
    SETTING='view/fullscreen_toolbar_position'

    def __init__(self,view):
        self.view=view;self.owner=o=view.owner;self.drag=None;self.settings_host=None
        self.position=o.color_settings.value(self.SETTING,'bottom')
        if not isinstance(self.position,str) or self.position not in self.POSITIONS:self.position='bottom'
        self.bar=QToolBar('全屏工具栏',o);self.bar.setObjectName('fullscreenToolbar')
        self.bar.setMovable(False);self.bar.setFloatable(False)
        self.bar.setAllowedAreas(Qt.ToolBarArea.AllToolBarAreas)
        self.bar.setStyleSheet('QToolBar{background:#fff;border:1px solid #dce5f1;padding:0;spacing:0;} QScrollArea{border:0;background:#fff;} QScrollBar:horizontal{height:9px;} QScrollBar:vertical{width:9px;}')
        self.root=ToolbarContents();self.outer=QBoxLayout(QBoxLayout.Direction.LeftToRight,self.root)
        self.outer.setContentsMargins(6,6,6,6);self.outer.setSpacing(4)
        self.grip=DragGrip(self);self.outer.addWidget(self.grip,0,Qt.AlignmentFlag.AlignCenter)
        self.scroller=QScrollArea();self.scroller.setWidgetResizable(True);self.scroller.setFrameShape(QFrame.Shape.NoFrame)
        self.scroller.setMinimumSize(0,0);self.outer.addWidget(self.scroller,1)
        self.content=QWidget();self.content.setStyleSheet('background:white;');self.body=QBoxLayout(QBoxLayout.Direction.LeftToRight,self.content)
        self.body.setContentsMargins(0,0,0,0);self.body.setSpacing(8)
        self.tools=QWidget();self.tools_layout=QBoxLayout(QBoxLayout.Direction.LeftToRight,self.tools)
        self.tools_layout.setContentsMargins(0,0,0,0);self.tools_layout.setSpacing(4)
        self.buttons={}
        for key,action in o.tools.items():
            label='胶带' if key=='tape' else action.text()
            b=FullscreenButton(key,label,action);self.buttons[key]=b;self.tools_layout.addWidget(b)
        self.body.addWidget(self.tools,0,Qt.AlignmentFlag.AlignCenter)
        self.commands=QWidget();self.commands_layout=QGridLayout(self.commands)
        self.commands_layout.setContentsMargins(0,0,0,0);self.commands_layout.setSpacing(4)
        self.undo=FullscreenButton('undo',action=o.undo_action)
        self.redo=FullscreenButton('redo',action=o.redo_action)
        self.save=FullscreenButton('save',action=o.save_action)
        self.page_manager=FullscreenButton('pages',action=o.page_toggle_action)
        self.corner=QFrame(o.scroll.viewport());self.corner.setObjectName('fullscreenCorner')
        self.corner.setAccessibleName('全屏快捷操作')
        self.corner.setStyleSheet('QFrame#fullscreenCorner{background:#fff;border:1px solid #dce5f1;border-radius:12px;}')
        self.corner_layout=QHBoxLayout(self.corner);self.corner_layout.setContentsMargins(6,6,6,6);self.corner_layout.setSpacing(4)
        self.corner.hide()
        self.options=FullscreenButton('options');self.options.setAccessibleName('当前工具设置')
        self.options.setToolTip('颜色、笔宽及当前工具设置');self.options.clicked.connect(self.show_settings)
        self.tools_layout.addWidget(self.options,0,Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.commands,0,Qt.AlignmentFlag.AlignCenter)
        self.scroller.setWidget(self.content)
        self.footer=QWidget();self.footer_layout=footer=QBoxLayout(QBoxLayout.Direction.LeftToRight,self.footer)
        footer.setContentsMargins(0,0,0,0);footer.setSpacing(4)
        self.position_button=FullscreenButton('position');self.position_button.setAccessibleName('全屏工具栏位置')
        self.position_button.setToolTip('工具栏位置：顶部、底部、左侧或右侧；也可拖动握柄')
        self.position_menu=QMenu(self.position_button);style_menu(self.position_menu)
        group=QActionGroup(self.position_menu);group.setExclusive(True);self.position_actions={}
        for key,(label,area) in self.POSITIONS.items():
            action=QAction(label,self.position_menu);action.setCheckable(True);group.addAction(action)
            action.triggered.connect(lambda checked=False,k=key:self.place(k));self.position_menu.addAction(action);self.position_actions[key]=action
        self.preference_menu=o.menus['设置'].addMenu('全屏工具栏位置');style_menu(self.preference_menu)
        self.preference_menu.addActions(list(self.position_actions.values()))
        self.position_button.setMenu(self.position_menu);self.position_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.exit=FullscreenButton('collapse',action=view.action)
        footer.addWidget(self.position_button);footer.addWidget(self.exit)
        self.outer.addWidget(self.footer,0,Qt.AlignmentFlag.AlignCenter)
        self.bar.addWidget(self.root);self.bar.hide();o.addToolBar(self.POSITIONS[self.position][1],self.bar)
        self.preview=DockPreview(o)
        self.popup=QFrame(o,Qt.WindowType.Popup);self.popup.setObjectName('fullscreenSettings')
        self.popup.setStyleSheet(o.editor_panel.styleSheet()+' QFrame#fullscreenSettings{background:white;border:1px solid #cbd5e1;border-radius:12px;}')
        popup_layout=QVBoxLayout(self.popup);popup_layout.setContentsMargins(12,8,12,10);popup_layout.setSpacing(4)
        header=QHBoxLayout();self.title=QLabel();header.addWidget(self.title);header.addStretch()
        close=QToolButton();close.setText('关闭');close.setMinimumSize(44,36);close.clicked.connect(self.popup.hide);header.addWidget(close)
        popup_layout.addLayout(header)
        self.settings_scroll=QScrollArea();self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame);self.settings_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        popup_layout.addWidget(self.settings_scroll)
        o.editor_panel.settings.currentChanged.connect(self.sync_settings)
        for action in o.tools.values():action.toggled.connect(self.sync_settings)
        o.gpu.changed.connect(self.sync_commands,Qt.ConnectionType.QueuedConnection)
        self.apply_layout()

    def apply_layout(self):
        side=self.position in ('left','right');self.root.side=side
        for widget in (self.content,self.tools,self.commands):widget.setMinimumSize(0,0)
        direction=QBoxLayout.Direction.TopToBottom if side else QBoxLayout.Direction.LeftToRight
        self.outer.setDirection(direction);self.body.setDirection(direction);self.tools_layout.setDirection(direction)
        self.footer_layout.setDirection(direction)
        self.outer.setContentsMargins(4 if side else 6,6,4 if side else 6,6)
        for button in self.buttons.values():
            button.compact=side;button.setFixedSize(44,48) if side else button.setFixedSize(64,60);button.update()
        self.commands.hide()
        for widget in (self.undo,self.redo,self.save,self.page_manager):
            self.commands_layout.removeWidget(widget);self.corner_layout.removeWidget(widget);self.footer_layout.removeWidget(widget)
        if side:
            for widget in (self.undo,self.redo,self.save,self.page_manager):self.corner_layout.addWidget(widget);widget.show()
        else:
            for index,widget in enumerate((self.undo,self.redo,self.save,self.page_manager)):
                self.footer_layout.insertWidget(index,widget);widget.show()
        if side:
            self.root.setMinimumSize(64,0);self.root.setMaximumSize(64,16777215)
            self.root.setSizePolicy(QSizePolicy.Policy.Fixed,QSizePolicy.Policy.Expanding)
            self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        else:
            self.root.setMinimumSize(0,76);self.root.setMaximumSize(16777215,76)
            self.root.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            self.scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for widget,layout in ((self.tools,self.tools_layout),(self.commands,self.commands_layout),(self.content,self.body)):
            layout.invalidate();widget.setMinimumSize(layout.minimumSize());widget.updateGeometry()
        self.outer.invalidate();self.root.updateGeometry()
        for key,action in self.position_actions.items():action.setChecked(key==self.position)
        self.sync_commands()

    def sync_commands(self,*args):
        if sip.isdeleted(self.owner):return
        visible=self.view.saved is not None and self.position in ('left','right') and not self.bar.isHidden()
        self.corner.setVisible(visible)
        if visible:
            self.corner_layout.invalidate();self.corner.setFixedSize(self.corner_layout.sizeHint())
            viewport=self.owner.scroll.viewport()
            self.corner.move(max(4,viewport.width()-self.corner.width()-12),12)
            self.corner.raise_()

    def enter(self):
        settings=self.owner.editor_panel.settings;self.settings_minimum=settings.minimumWidth()
        self.owner.editor_panel.layout().removeWidget(settings);self.settings_scroll.setWidget(settings)
        self.settings_host=settings;self.sync_settings();self.bar.show();self.sync_commands()

    def leave(self):
        self.cancel_drag();self.popup.hide();self.bar.hide();self.corner.hide()
        if self.settings_host is not None:
            settings=self.settings_scroll.takeWidget();settings.setMinimumWidth(self.settings_minimum)
            self.owner.editor_panel.layout().addWidget(settings);settings.show();self.settings_host=None

    def sync_settings(self,*args):
        if self.settings_host is None:return
        settings=self.settings_host;page=settings.currentWidget()
        if page and page.layout():settings.setMinimumWidth(max(360,page.layout().minimumSize().width()))
        current=next((a.text() for a in self.owner.tools.values() if a.isChecked()),'工具')
        self.title.setText(current+'设置')

    def show_settings(self):
        if self.view.saved is None or self.settings_host is None or self.view.busy_gesture():return
        if not self.settings_host.isEnabled():return
        self.sync_settings();self.popup.resize(min(1000,max(320,self.owner.width()-32)),130)
        anchor=self.options.mapToGlobal(self.options.rect().center())
        if self.position=='bottom':point=QPoint(anchor.x()-self.popup.width()//2,self.bar.mapToGlobal(QPoint()).y()-self.popup.height()-8)
        elif self.position=='top':point=QPoint(anchor.x()-self.popup.width()//2,self.bar.mapToGlobal(QPoint(0,self.bar.height())).y()+8)
        elif self.position=='left':point=QPoint(self.bar.mapToGlobal(QPoint(self.bar.width(),0)).x()+8,anchor.y()-self.popup.height()//2)
        else:point=QPoint(self.bar.mapToGlobal(QPoint()).x()-self.popup.width()-8,anchor.y()-self.popup.height()//2)
        screen=QApplication.screenAt(anchor) or self.owner.screen();available=screen.availableGeometry()
        point.setX(max(available.left()+8,min(point.x(),available.right()-self.popup.width()-7)))
        point.setY(max(available.top()+8,min(point.y(),available.bottom()-self.popup.height()-7)))
        self.popup.move(point);self.popup.show();self.popup.raise_()

    def place(self,position):
        if not isinstance(position,str) or position not in self.POSITIONS:return False
        if self.view.busy_gesture():
            for key,action in self.position_actions.items():action.setChecked(key==self.position)
            return False
        if position!=self.position:
            fullscreen=self.view.saved is not None
            self.popup.hide()
            if fullscreen:self.view.capture_anchor()
            self.position=position
            self.owner.addToolBar(self.POSITIONS[position][1],self.bar);self.apply_layout();self.bar.setVisible(fullscreen)
            self.sync_commands()
            if fullscreen:self.view.restore_anchor()
        self.owner.color_settings.setValue(self.SETTING,position);self.owner.color_settings.sync()
        return True

    def press(self,point):
        if self.view.saved is None or self.view.busy_gesture():return
        self.drag={'start':point,'active':False,'candidate':self.position}

    def move(self,point):
        if self.drag is None:return
        if not self.drag['active']:
            if (point-self.drag['start']).manhattanLength()<QApplication.startDragDistance():return
            self.drag['active']=True;self.popup.hide();self.grip.grabMouse();self.grip.setCursor(Qt.CursorShape.ClosedHandCursor)
        local=self.owner.mapFromGlobal(point);rect=self.owner.rect()
        if not rect.contains(local):
            self.drag['candidate']=None;self.preview.hide();return
        distances={'left':abs(local.x()-rect.left()),'right':abs(local.x()-rect.right()),'top':abs(local.y()-rect.top()),'bottom':abs(local.y()-rect.bottom())}
        candidate=min(distances,key=distances.get)
        self.drag['candidate']=candidate
        bounds=rect.adjusted(6,6,-6,-6)
        if candidate=='bottom':bounds.setTop(max(bounds.top(),bounds.bottom()-75))
        elif candidate=='top':bounds.setBottom(min(bounds.bottom(),bounds.top()+75))
        elif candidate=='left':bounds.setRight(min(bounds.right(),bounds.left()+63))
        else:bounds.setLeft(max(bounds.left(),bounds.right()-63))
        self.preview.caption=('松开后移到' if candidate in ('top','bottom') else '松开后\n移到')+self.POSITIONS[candidate][0]
        self.preview.setGeometry(bounds);self.preview.show();self.preview.raise_();self.preview.update()

    def release(self,point):
        if self.drag is None:return
        active=self.drag['active']
        if active:self.move(point)
        candidate=self.drag['candidate'];self.cancel_drag()
        if active:self.place(candidate)

    def cancel_drag(self):
        drag=self.drag;self.drag=None;self.preview.hide()
        if drag and drag['active'] and QWidget.mouseGrabber() is self.grip:self.grip.releaseMouse()
        self.grip.setCursor(Qt.CursorShape.OpenHandCursor)
        if drag:self.view.schedule_cursor_refresh()
        return bool(drag)
